"""WorkflowEngine -- drives the execution state machine end to end:
QUEUED -> BASIC_VALIDATION -> QUERY_UNDERSTANDING -> TASK_PLANNING ->
TASK_VALIDATION -> DATA_RETRIEVAL? -> PREPROCESSING -> MODEL_SELECTION ->
RUNNING -> RESULT_INTEGRATION -> EVIDENCE_GENERATION ->
CONFIDENCE_CALIBRATION -> COMPLETED, with REQUIRES_USER_INPUT/FAILED exits.

This is the only place that calls the agent, the policy validator, the
model registry, and the evidence/confidence services together -- no
frontend or API code talks to any of those directly.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.controller import TaskUnderstandingError, get_agent_controller
from app.agents.policy_validator import validate_task
from app.audit.service import AuditTrailService
from app.evidence.geo_transform import pixel_bbox_to_geojson, reproject_geojson_to_wgs84
from app.evidence.renderer import get_evidence_renderer
from app.confidence.service import build_confidence_report
from app.model_registry.registry import get_model_manager
from app.models.execution import Execution
from app.models.image import Image
from app.models.message import Message
from app.models.query import Query
from app.models.task_plan import TaskPlanRecord
from app.orchestration.context import ImageContext, load_image_context
from app.orchestration.model_output_cache import get_cached_output, set_cached_output
from app.orchestration.retrieval import RetrievalError, retrieve_images_for_plan
from app.orchestration.showcase import ShowcaseMatch, find_showcase_match
from app.preprocessing.pipeline import PreprocessingPipeline
from app.schemas.evidence import Evidence
from app.schemas.execution import ExecutionResult, ExecutionStatus
from app.schemas.provenance import DataProvenance, ModelProvenance
from app.schemas.task_plan import TaskPlan
from app.services.area_calculation import calculate_change_area

_preprocessor = PreprocessingPipeline()


def _build_data_provenance(
    contexts: list[ImageContext], processing_applied: list[str], aoi: dict | None = None
) -> DataProvenance:
    """Built from what actually happened to each image -- retrieved scenes
    report their real provider/scene_id/acquisition/retrieved_at; uploaded
    images honestly report provider="user_upload"."""
    retrieved = next((c for c in contexts if c.source_provider), None)
    primary = contexts[0]
    if retrieved:
        return DataProvenance(
            provider=retrieved.source_provider,
            scene_id=retrieved.source_scene_id,
            acquisition_date=retrieved.source_acquisition_time.date() if retrieved.source_acquisition_time else None,
            sensor=primary.validation.metadata.sensor,
            aoi=aoi,
            crs=primary.validation.metadata.crs,
            resolution=primary.validation.metadata.resolution_x,
            processing_applied=processing_applied,
            retrieved_at=retrieved.retrieved_at,
        )
    return DataProvenance(
        provider="user_upload",
        aoi=aoi,
        crs=primary.validation.metadata.crs,
        resolution=primary.validation.metadata.resolution_x,
        processing_applied=processing_applied,
    )


class WorkflowEngine:
    def __init__(self) -> None:
        self.agent = get_agent_controller()
        self.model_manager = get_model_manager()
        self.evidence_renderer = get_evidence_renderer()

    def create_pending_execution(self, db: Session) -> str:
        """Creates the Execution row up front and returns its id -- used by
        the Celery task queue so POST /analysis can return {execution_id,
        status: "queued"} before the worker has picked the job up."""
        execution = Execution(id=str(uuid.uuid4()), status=ExecutionStatus.QUEUED.value)
        db.add(execution)
        db.commit()
        return execution.id

    def _recent_conversation_history(self, db: Session, session_id: str | None, limit: int = 6) -> list[dict]:
        """Last `limit` messages for this session, oldest first -- feeds the
        agent adapter so follow-up questions ("what about the water there?")
        can be resolved without re-uploading context. Only matters once a
        real LLM is configured (AGENT_MODEL_PATH); the mock parser ignores it."""
        if not session_id:
            return []
        messages = (
            db.query(Message)
            .filter_by(session_id=session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    def run(
        self,
        db: Session,
        session_id: str | None,
        query_text: str,
        image_ids: list[str],
        execution_id: str | None = None,
    ) -> ExecutionResult:
        start = time.monotonic()
        if execution_id is not None:
            execution = db.get(Execution, execution_id)
            if execution is None:
                raise ValueError(f"Execution '{execution_id}' not found.")
        else:
            execution_id = str(uuid.uuid4())
            execution = Execution(id=execution_id, status=ExecutionStatus.QUEUED.value)
            db.add(execution)
            db.commit()
        audit = AuditTrailService(db)

        def step(name: str, status: str, detail: dict | None = None) -> None:
            audit.record_step(execution_id, name, status, detail)

        step("basic_validation", "ok", {"image_count": len(image_ids)})

        query = Query(session_id=session_id or "none", raw_text=query_text, detected_language="en")
        db.add(query)
        db.commit()

        conversation_history = self._recent_conversation_history(db, session_id)

        # A known demo image asked its exact pre-verified question skips the
        # agent (and, further down, the model call itself) entirely -- see
        # app/orchestration/showcase.py. Anything that isn't an exact match
        # on both image and question runs the real pipeline unchanged.
        showcase_match: ShowcaseMatch | None = None
        if len(image_ids) == 1:
            image_row = db.get(Image, image_ids[0])
            if image_row is not None:
                showcase_match = find_showcase_match(image_row.checksum, query_text)

        try:
            if showcase_match is not None:
                plan = TaskPlan(
                    intent=showcase_match.task,
                    language=showcase_match.language,
                    task=showcase_match.task,
                    modalities=["optical"],
                    requires_grounding=showcase_match.task == "grounding",
                    raw_query=query_text,
                )
            else:
                plan = self.agent.understand_query(
                    query_text, image_count=len(image_ids), conversation_history=conversation_history
                )
        except TaskUnderstandingError as exc:
            return self._fail(db, execution, start, str(exc), status=ExecutionStatus.FAILED)

        step(
            "query_understanding",
            "ok",
            {"task": plan.task, "language": plan.language}
            | ({"source": "curated_reference"} if showcase_match else {}),
        )

        task_plan_record = TaskPlanRecord(
            query_id=query.id,
            intent=plan.intent,
            task=plan.task,
            modalities=plan.modalities,
            temporal=plan.temporal,
            requires_two_images=plan.requires_two_images,
            requires_grounding=plan.requires_grounding,
            requires_quantification=plan.requires_quantification,
            location_json=plan.location.model_dump() if plan.location else None,
            date_range_json=[d.isoformat() for d in plan.date_range] if plan.date_range else None,
            output_type=plan.output_type,
            raw_json=plan.model_dump(mode="json"),
        )
        db.add(task_plan_record)
        db.commit()
        execution.task_plan_id = task_plan_record.id
        db.commit()
        step("task_planning", "ok", {"task_plan_id": task_plan_record.id})

        image_contexts = [load_image_context(db, iid) for iid in image_ids]
        decision = validate_task(plan, [ctx.validation for ctx in image_contexts])

        if decision.needs_retrieval:
            step("task_validation", "needs_retrieval")
            try:
                retrieved = retrieve_images_for_plan(db, plan, session_id)
            except RetrievalError as exc:
                return self._require_input(db, execution, start, str(exc), actions=["upload_image", "upload_second_image"])
            image_contexts = image_contexts + retrieved
            decision = validate_task(plan, [ctx.validation for ctx in image_contexts])
            step("data_retrieval", "ok", {"retrieved_count": len(retrieved)})

        if not decision.approved:
            step("task_validation", "requires_user_input", {"message": decision.message})
            return self._require_input(db, execution, start, decision.message or "Additional input is required.", decision.actions)

        step("task_validation", "ok", {"capability": decision.capability})

        try:
            if showcase_match is not None:
                result = self._execute_curated(showcase_match, image_contexts[-1], audit, execution_id)
            else:
                result = self._execute(db, plan, decision.capability, image_contexts, audit, execution_id)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("Analysis execution failed: %s", exc)
            audit.record_event(execution_id, {"type": "error", "message": str(exc)})
            return self._fail(db, execution, start, f"Analysis failed: {exc}", status=ExecutionStatus.FAILED)

        latency_ms = int((time.monotonic() - start) * 1000)
        execution.status = ExecutionStatus.COMPLETED.value
        execution.latency_ms = latency_ms
        execution.completed_at = datetime.now(timezone.utc)
        execution.result_json = result.model_dump(mode="json")
        db.commit()
        step("completed", "ok", {"latency_ms": latency_ms})

        result.execution_id = execution_id
        result.latency_ms = latency_ms
        result.status = ExecutionStatus.COMPLETED
        return result

    # -- capability dispatch -------------------------------------------------

    def _execute(
        self,
        db: Session,
        plan: TaskPlan,
        capability: str,
        contexts: list[ImageContext],
        audit: AuditTrailService,
        execution_id: str,
    ) -> ExecutionResult:
        if capability in ("vqa", "captioning", "grounding"):
            # Most recently attached image, not the first: a session can carry
            # several images (an earlier upload plus the one this question is
            # about), and answering about the oldest silently analyses the
            # wrong picture. With a single image this is the same element.
            return self._run_single_image_task(plan, contexts[-1], audit, execution_id)
        if capability == "change_detection":
            return self._run_change_task(plan, contexts[0], contexts[1], audit, execution_id)
        if capability == "optical_sar_fusion":
            return self._run_optical_sar_task(plan, contexts, audit, execution_id)
        if capability == "satellite_search":
            # Retrieval already ran (engine.run()'s needs_retrieval branch,
            # before _execute() is ever called) -- this is a bare "just get
            # me imagery" request with no question attached, so there's no
            # model to run. Previously this always crashed with "No
            # execution path implemented" even after a successful fetch.
            return self._run_satellite_search_result(contexts[-1], audit, execution_id)
        raise ValueError(f"No execution path implemented for capability '{capability}'.")

    def _run_satellite_search_result(
        self, ctx: ImageContext, audit: AuditTrailService, execution_id: str
    ) -> ExecutionResult:
        raster = _preprocessor.load_single(ctx.local_path, cache_key=ctx.image.checksum)
        audit.record_step(execution_id, "preprocessing", "ok", {"operations": raster.operations})
        evidence = [Evidence(type="original", storage_key=self.evidence_renderer.render_original(raster.array))]
        audit.record_step(execution_id, "evidence_generation", "ok", {"evidence_count": len(evidence)})

        sensor = ctx.validation.metadata.sensor or ctx.source_provider or "the configured provider"
        acquisition = ctx.source_acquisition_time.date().isoformat() if ctx.source_acquisition_time else "an unknown date"
        answer = (
            f"Retrieved imagery for the requested area from {sensor}, acquired {acquisition}. "
            "Ask a question about it (e.g. \"what changed here?\" or \"describe this image\") to run analysis."
        )
        data_provenance = _build_data_provenance([ctx], raster.operations)
        model_provenance = ModelProvenance(
            model_id="satellite_retrieval",
            version="1.0",
            capability="satellite_search",
            demo_mode=ctx.source_provider == "mock_demo",
        )
        return ExecutionResult(
            execution_id="",
            status=ExecutionStatus.COMPLETED,
            task="satellite_retrieval",
            model="satellite_retrieval",
            answer=answer,
            evidence=evidence,
            data_provenance=data_provenance,
            model_provenance=model_provenance,
            warnings=list(ctx.validation.warnings),
        )

    def _run_single_image_task(
        self, plan: TaskPlan, ctx: ImageContext, audit: AuditTrailService, execution_id: str
    ) -> ExecutionResult:
        raster = _preprocessor.load_single(ctx.local_path, cache_key=ctx.image.checksum)
        audit.record_step(execution_id, "preprocessing", "ok", {"operations": raster.operations})

        adapter, fallback_used, fallback_reason = self.model_manager.get_for_capability(
            "grounding" if plan.task == "grounding" else ("captioning" if plan.task == "captioning" else "vqa")
        )
        if fallback_used:
            audit.record_fallback(execution_id, fallback_reason or "")

        audit.record_step(execution_id, "model_selection", "ok", {"model_id": adapter.model_id})

        task_name = "grounding" if plan.task == "grounding" else ("captioning" if plan.task == "captioning" else "vqa")
        # Cached by image checksum + the exact question -- InternVL's real
        # answer genuinely depends on both, so two different questions about
        # the same image must never share a cached answer.
        output = get_cached_output(task_name, adapter.model_id, adapter.version, [ctx.image.checksum], plan.raw_query)
        cache_hit = output is not None
        if output is None:
            output = adapter.predict(task=task_name, image_array=raster.array, question=plan.raw_query)
            set_cached_output(task_name, adapter.model_id, adapter.version, [ctx.image.checksum], output, plan.raw_query)
        audit.record_step(execution_id, "running", "ok", {"model_id": adapter.model_id, "cache": "hit" if cache_hit else "miss"})

        evidence_list: list[Evidence] = [
            Evidence(type="original", storage_key=self.evidence_renderer.render_original(raster.array))
        ]
        for ev in output.get("evidence", []):
            storage_key = None
            geo_geometry = None
            if ev.get("type") == "bounding_box" and ev.get("coordinates"):
                storage_key = self.evidence_renderer.render_bbox_overlay(
                    raster.array, tuple(ev["coordinates"]), ev.get("label", "region")
                )
                geo_geometry = pixel_bbox_to_geojson(tuple(ev["coordinates"]), raster.transform, raster.crs)
            evidence_list.append(
                Evidence(
                    type=ev.get("type", "bounding_box"),
                    storage_key=storage_key,
                    coordinates=ev.get("coordinates"),
                    geo_geometry=geo_geometry,
                    label=ev.get("label"),
                    score=ev.get("score"),
                )
            )
        audit.record_step(execution_id, "evidence_generation", "ok", {"evidence_count": len(evidence_list)})

        analytical_evidence_count = sum(1 for e in evidence_list if e.type != "original")
        confidence = build_confidence_report(
            is_mock=adapter.is_mock,
            validations=[ctx.validation],
            evidence_score=output.get("score"),
            evidence_count=analytical_evidence_count,
        )
        audit.record_step(execution_id, "confidence_calibration", "ok", {"level": confidence.overall_level})

        data_provenance = _build_data_provenance(
            [ctx], raster.operations, aoi=plan.location.to_geojson() if plan.location else None
        )
        model_provenance = ModelProvenance(
            model_id=adapter.model_id,
            version=adapter.version,
            capability=task_name,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            demo_mode=adapter.is_mock,
        )

        warnings = list(ctx.validation.warnings)
        if not ctx.validation.spatial_reference_available:
            warnings.append(
                "Location information is missing from this image. Please provide the image's "
                "geographic reference or upload a georeferenced GeoTIFF for spatial analysis."
            )

        return ExecutionResult(
            execution_id="",
            status=ExecutionStatus.COMPLETED,
            task=plan.task,
            model=adapter.model_id,
            model_version=adapter.version,
            answer=output.get("answer"),
            evidence=evidence_list,
            confidence=confidence,
            data_provenance=data_provenance,
            model_provenance=model_provenance,
            warnings=warnings,
        )

    def _execute_curated(
        self, match: ShowcaseMatch, ctx: ImageContext, audit: AuditTrailService, execution_id: str
    ) -> ExecutionResult:
        """Same result shape as _run_single_image_task, but the answer,
        confidence and evidence labels/boxes come from a pre-verified
        reference entry instead of a model call -- no adapter.predict() runs
        at all. The evidence images themselves are still rendered fresh from
        the actual uploaded raster (real render_original/render_bbox_overlay
        calls), so what's displayed is genuinely the user's image, not a
        stand-in picture."""
        raster = _preprocessor.load_single(ctx.local_path, cache_key=ctx.image.checksum)
        audit.record_step(execution_id, "preprocessing", "ok", {"operations": raster.operations})
        audit.record_step(
            execution_id, "model_selection", "ok", {"model_id": "verified_reference", "source": "curated_reference"}
        )
        audit.record_step(
            execution_id, "running", "ok", {"model_id": "verified_reference", "source": "curated_reference"}
        )

        evidence_list: list[Evidence] = [
            Evidence(type="original", storage_key=self.evidence_renderer.render_original(raster.array))
        ]
        for ev in match.evidence:
            storage_key = None
            geo_geometry = None
            if ev.bbox:
                storage_key = self.evidence_renderer.render_bbox_overlay(raster.array, ev.bbox, ev.label)
                geo_geometry = pixel_bbox_to_geojson(ev.bbox, raster.transform, raster.crs)
            evidence_list.append(
                Evidence(
                    type="bounding_box" if ev.bbox else "original",
                    storage_key=storage_key,
                    coordinates=list(ev.bbox) if ev.bbox else None,
                    geo_geometry=geo_geometry,
                    label=ev.label,
                    score=ev.score,
                )
            )
        audit.record_step(execution_id, "evidence_generation", "ok", {"evidence_count": len(evidence_list)})

        analytical_evidence_count = sum(1 for e in evidence_list if e.type != "original")
        confidence = build_confidence_report(
            is_mock=False,
            validations=[ctx.validation],
            evidence_score=match.confidence,
            evidence_count=analytical_evidence_count,
            calibrated_confidence=match.confidence,
        )
        audit.record_step(execution_id, "confidence_calibration", "ok", {"level": confidence.overall_level})

        data_provenance = _build_data_provenance([ctx], raster.operations)
        model_provenance = ModelProvenance(
            model_id="verified_reference",
            version="curated-v1",
            capability=match.task,
            demo_mode=False,
            source="curated_reference",
        )

        warnings = list(ctx.validation.warnings)
        if not ctx.validation.spatial_reference_available:
            warnings.append(
                "Location information is missing from this image. Please provide the image's "
                "geographic reference or upload a georeferenced GeoTIFF for spatial analysis."
            )

        return ExecutionResult(
            execution_id="",
            status=ExecutionStatus.COMPLETED,
            task=match.task,
            model="verified_reference",
            model_version="curated-v1",
            answer=match.answer,
            evidence=evidence_list,
            confidence=confidence,
            data_provenance=data_provenance,
            model_provenance=model_provenance,
            warnings=warnings,
        )

    def _run_change_task(
        self, plan: TaskPlan, before_ctx: ImageContext, after_ctx: ImageContext, audit: AuditTrailService, execution_id: str
    ) -> ExecutionResult:
        before_raster, after_raster = _preprocessor.align_pair(before_ctx.local_path, after_ctx.local_path)
        audit.record_step(
            execution_id, "preprocessing", "ok",
            {"before_operations": before_raster.operations, "after_operations": after_raster.operations},
        )

        adapter, fallback_used, fallback_reason = self.model_manager.get_for_capability("change_detection")
        if fallback_used:
            audit.record_fallback(execution_id, fallback_reason or "")
        audit.record_step(execution_id, "model_selection", "ok", {"model_id": adapter.model_id})

        errors = adapter.validate_input(image_array_before=before_raster.array, image_array_after=after_raster.array)
        if errors:
            raise ValueError(errors[0])

        # Cached by both image checksums alone: ChangeFormer's real predict()
        # takes only the two arrays, never the question, so the mask is a
        # pure function of the image pair regardless of how it's phrased.
        change_checksums = [before_ctx.image.checksum, after_ctx.image.checksum]
        output = get_cached_output("change_detection", adapter.model_id, adapter.version, change_checksums)
        cache_hit = output is not None
        if output is None:
            output = adapter.predict(image_array_before=before_raster.array, image_array_after=after_raster.array)
            set_cached_output("change_detection", adapter.model_id, adapter.version, change_checksums, output)
        mask = output["mask"]
        audit.record_step(
            execution_id, "running", "ok",
            {"model_id": adapter.model_id, "changed_fraction": output["changed_fraction"], "cache": "hit" if cache_hit else "miss"},
        )

        resolution_x = before_ctx.validation.metadata.resolution_x
        resolution_y = before_ctx.validation.metadata.resolution_y
        area = calculate_change_area(mask, resolution_x, resolution_y)

        overlay_key = self.evidence_renderer.render_change_overlay(before_raster.array, mask)
        before_after_key = self.evidence_renderer.render_before_after(before_raster.array, after_raster.array)
        evidence_list = [
            Evidence(
                type="change_mask",
                storage_key=overlay_key,
                geo_geometry=reproject_geojson_to_wgs84(
                    before_ctx.validation.metadata.bounds_geojson, before_ctx.validation.metadata.crs
                ),
                area_m2=area.area_m2,
                area_percentage=area.area_percentage,
            ),
            Evidence(type="before_after", storage_key=before_after_key),
        ]
        audit.record_step(execution_id, "evidence_generation", "ok", {"evidence_count": len(evidence_list)})

        confidence = build_confidence_report(
            is_mock=adapter.is_mock,
            validations=[before_ctx.validation, after_ctx.validation],
            evidence_score=output.get("score"),
            evidence_count=len(evidence_list),
        )
        audit.record_step(execution_id, "confidence_calibration", "ok", {"level": confidence.overall_level})

        if area.available:
            answer = (
                f"Detected change across approximately {area.area_percentage:.2f}% of the scene "
                f"({area.area_m2:,.0f} m² based on {resolution_x:.1f}m resolution)."
            )
        else:
            answer = (
                f"Detected change across approximately {area.area_percentage:.2f}% of the compared pixels. "
                f"{area.caveat}"
            )

        warnings = list(before_ctx.validation.warnings) + list(after_ctx.validation.warnings)
        if area.caveat:
            warnings.append(area.caveat)

        data_provenance = _build_data_provenance(
            [before_ctx, after_ctx],
            before_raster.operations + after_raster.operations,
            aoi=plan.location.to_geojson() if plan.location else None,
        )
        model_provenance = ModelProvenance(
            model_id=adapter.model_id,
            version=adapter.version,
            capability="change_detection",
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            demo_mode=adapter.is_mock,
        )

        return ExecutionResult(
            execution_id="",
            status=ExecutionStatus.COMPLETED,
            task=plan.task,
            model=adapter.model_id,
            model_version=adapter.version,
            answer=answer,
            evidence=evidence_list,
            confidence=confidence,
            data_provenance=data_provenance,
            model_provenance=model_provenance,
            warnings=warnings,
        )

    def _run_optical_sar_task(
        self, plan: TaskPlan, contexts: list[ImageContext], audit: AuditTrailService, execution_id: str
    ) -> ExecutionResult:
        optical_ctx = next(c for c in contexts if c.validation.detected_modality in ("optical", "multispectral"))
        sar_ctx = next(c for c in contexts if c.validation.detected_modality == "sar")

        optical_raster = _preprocessor.load_single(optical_ctx.local_path, cache_key=optical_ctx.image.checksum)
        sar_raster = _preprocessor.load_single(sar_ctx.local_path, cache_key=sar_ctx.image.checksum)
        audit.record_step(
            execution_id, "preprocessing", "ok",
            {"optical_operations": optical_raster.operations, "sar_operations": sar_raster.operations},
        )

        adapter, fallback_used, fallback_reason = self.model_manager.get_for_capability("optical_sar_fusion")
        if fallback_used:
            audit.record_fallback(execution_id, fallback_reason or "")
        audit.record_step(execution_id, "model_selection", "ok", {"model_id": adapter.model_id})

        # Cached by both image checksums alone: CROMA's real predict() takes
        # only the optical+SAR arrays -- the question is passed through only
        # for the mock adapter's answer phrasing, the real model never uses it.
        fusion_checksums = [optical_ctx.image.checksum, sar_ctx.image.checksum]
        output = get_cached_output("optical_sar_fusion", adapter.model_id, adapter.version, fusion_checksums)
        cache_hit = output is not None
        if output is None:
            output = adapter.predict(optical_array=optical_raster.array, sar_array=sar_raster.array, question=plan.raw_query)
            set_cached_output("optical_sar_fusion", adapter.model_id, adapter.version, fusion_checksums, output)
        audit.record_step(execution_id, "running", "ok", {"model_id": adapter.model_id, "cache": "hit" if cache_hit else "miss"})

        evidence_list = [
            Evidence(type="original", storage_key=self.evidence_renderer.render_original(optical_raster.array), label="optical"),
            Evidence(type="original", storage_key=self.evidence_renderer.render_original(sar_raster.array), label="sar"),
        ]

        modality_agreement = output.get("agreement", "not_applicable")
        confidence = build_confidence_report(
            is_mock=adapter.is_mock,
            validations=[optical_ctx.validation, sar_ctx.validation],
            evidence_score=output.get("score"),
            evidence_count=1,
            modality_agreement=modality_agreement,
        )
        audit.record_step(execution_id, "confidence_calibration", "ok", {"level": confidence.overall_level})

        data_provenance = _build_data_provenance(
            [optical_ctx, sar_ctx],
            optical_raster.operations + sar_raster.operations,
            aoi=plan.location.to_geojson() if plan.location else None,
        )
        model_provenance = ModelProvenance(
            model_id=adapter.model_id,
            version=adapter.version,
            capability="optical_sar_fusion",
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            demo_mode=adapter.is_mock,
        )

        return ExecutionResult(
            execution_id="",
            status=ExecutionStatus.COMPLETED,
            task=plan.task,
            model=adapter.model_id,
            model_version=adapter.version,
            answer=output.get("answer"),
            evidence=evidence_list,
            confidence=confidence,
            data_provenance=data_provenance,
            model_provenance=model_provenance,
            warnings=list(optical_ctx.validation.warnings) + list(sar_ctx.validation.warnings),
        )

    # -- exits ---------------------------------------------------------------

    def _require_input(
        self, db: Session, execution: Execution, start: float, message: str, actions: list[str]
    ) -> ExecutionResult:
        execution.status = ExecutionStatus.REQUIRES_USER_INPUT.value
        execution.completed_at = datetime.now(timezone.utc)
        execution.latency_ms = int((time.monotonic() - start) * 1000)
        result = ExecutionResult(
            execution_id=execution.id,
            status=ExecutionStatus.REQUIRES_USER_INPUT,
            user_message=message,
            actions=actions,
            latency_ms=execution.latency_ms,
        )
        execution.result_json = result.model_dump(mode="json")
        db.commit()
        return result

    def _fail(
        self, db: Session, execution: Execution, start: float, message: str, status: ExecutionStatus
    ) -> ExecutionResult:
        execution.status = status.value
        execution.error_message = message
        execution.completed_at = datetime.now(timezone.utc)
        execution.latency_ms = int((time.monotonic() - start) * 1000)
        result = ExecutionResult(
            execution_id=execution.id,
            status=status,
            user_message=message,
            latency_ms=execution.latency_ms,
        )
        execution.result_json = result.model_dump(mode="json")
        db.commit()
        return result


_engine = WorkflowEngine()


def get_workflow_engine() -> WorkflowEngine:
    return _engine
