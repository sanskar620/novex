from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.execution import Execution, ExecutionStep
from app.models.report import Report
from app.reports.geojson_generator import generate_analysis_geojson
from app.reports.pdf_generator import generate_analysis_pdf
from app.schemas.execution import ExecutionResult
from app.services.analysis_service import submit_analysis
from app.storage.object_storage import get_storage_backend

router = APIRouter(prefix="/analysis", tags=["analysis"])


class RunAnalysisRequest(BaseModel):
    session_id: str | None = None
    query_text: str
    image_ids: list[str] = []


class RunAnalysisResponse(BaseModel):
    execution_id: str
    status: str


def _load_result(execution: Execution) -> ExecutionResult:
    data = dict(execution.result_json or {})
    data["execution_id"] = execution.id
    data["status"] = execution.status
    data["latency_ms"] = execution.latency_ms
    return ExecutionResult(**data)


@router.post("", response_model=RunAnalysisResponse)
def run_analysis(body: RunAnalysisRequest, db: Session = Depends(get_db)) -> RunAnalysisResponse:
    execution_id = submit_analysis(db, body.session_id, body.query_text, body.image_ids)
    execution = db.get(Execution, execution_id)
    return RunAnalysisResponse(execution_id=execution_id, status=execution.status if execution else "queued")


@router.get("/{execution_id}", response_model=ExecutionResult)
def get_analysis(execution_id: str, db: Session = Depends(get_db)) -> ExecutionResult:
    execution = db.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return _load_result(execution)


@router.get("/{execution_id}/evidence")
def get_evidence(execution_id: str, db: Session = Depends(get_db)) -> dict:
    execution = db.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return {"evidence": (execution.result_json or {}).get("evidence", [])}


def _completed_execution_or_404(execution_id: str, db: Session) -> Execution:
    execution = db.get(Execution, execution_id)
    if execution is None:
        if execution_id.startswith("exec-demo") or execution_id.startswith("demo-"):
            return Execution(
                id=execution_id,
                status="completed",
                result_json={
                    "task": "vqa",
                    "model": "Qwen3-8B Spatial Agent",
                    "model_version": "3.2.0-agent",
                    "answer": "Scene analysis complete: The satellite imagery exhibits mixed land use comprising vegetative cover (58%), transport corridors (18%), and residential-commercial parcels (24%). Geometric alignment and radiometry are calibrated.",
                    "evidence": [
                        {
                            "type": "polygon",
                            "label": "Primary Area of Interest",
                            "score": 0.92,
                            "area_m2": 2560000,
                            "area_percentage": 100,
                            "geo_geometry": {
                                "type": "Polygon",
                                "coordinates": [[[73.8567, 18.5204], [73.9142, 18.5204], [73.9142, 18.5789], [73.8567, 18.5789], [73.8567, 18.5204]]],
                            },
                        }
                    ],
                    "confidence": {
                        "mode": "calibrated",
                        "overall_level": "high",
                        "input_quality": "good",
                        "evidence_quality": "strong",
                    },
                    "data_provenance": {
                        "provider": "Copernicus Sentinel-1 SAR",
                        "scene_id": "S1A_IW_GRDH_1SDV",
                        "sensor": "Sentinel-1 C-SAR",
                    },
                    "model_provenance": {
                        "model_id": "qwen3_8b_spatial",
                        "version": "3.2.0-agent",
                        "demo_mode": True,
                    },
                },
            )
        raise HTTPException(status_code=404, detail="Execution not found.")
    if execution.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="A report can only be generated for a completed analysis.",
        )
    return execution


@router.get("/{execution_id}/report")
def get_report(execution_id: str, db: Session = Depends(get_db)) -> Response:
    execution = _completed_execution_or_404(execution_id, db)
    pdf_bytes = generate_analysis_pdf(db, execution)

    try:
        storage = get_storage_backend()
        storage_key = f"reports/{execution_id}.pdf"
        storage.put_bytes(storage_key, pdf_bytes, content_type="application/pdf")
        if db.get(Execution, execution_id) is not None:
            if not db.query(Report).filter_by(execution_id=execution_id, type="pdf").first():
                db.add(Report(execution_id=execution_id, type="pdf", storage_key=storage_key))
                db.commit()
    except Exception:
        db.rollback()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="satquery_{execution_id[:8]}.pdf"'},
    )


@router.get("/{execution_id}/geojson")
def get_geojson(execution_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    execution = _completed_execution_or_404(execution_id, db)
    geojson = generate_analysis_geojson(execution)

    try:
        storage = get_storage_backend()
        storage_key = f"reports/{execution_id}.geojson"
        storage.put_bytes(storage_key, json.dumps(geojson).encode("utf-8"), content_type="application/geo+json")
        if db.get(Execution, execution_id) is not None:
            if not db.query(Report).filter_by(execution_id=execution_id, type="geojson").first():
                db.add(Report(execution_id=execution_id, type="geojson", storage_key=storage_key))
                db.commit()
    except Exception:
        db.rollback()

    return JSONResponse(content=geojson, media_type="application/geo+json")


@router.get("/{execution_id}/transparency")
def get_transparency(execution_id: str, db: Session = Depends(get_db)) -> dict:
    """"How Was This Analyzed?" -- safe structured metadata only, never
    hidden chain-of-thought."""
    execution = db.get(Execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    steps = (
        db.query(ExecutionStep)
        .filter_by(execution_id=execution_id)
        .order_by(ExecutionStep.created_at.asc())
        .all()
    )
    result = execution.result_json or {}
    return {
        "task": result.get("task"),
        "model": result.get("model"),
        "model_version": result.get("model_version"),
        "data_provenance": result.get("data_provenance"),
        "model_provenance": result.get("model_provenance"),
        "confidence": result.get("confidence"),
        "warnings": result.get("warnings", []),
        "processing_steps": [
            {"step": s.step_name, "status": s.status, "detail": s.detail_json} for s in steps
        ],
    }
