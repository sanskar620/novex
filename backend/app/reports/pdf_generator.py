"""PDF report generation via ReportLab. Renders exactly what's in the
stored ExecutionResult/audit trail -- never hidden chain-of-thought,
never a number that wasn't actually computed.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.orm import Session

from app.models.execution import Execution
from app.models.query import Query
from app.models.task_plan import TaskPlanRecord
from app.storage.object_storage import get_storage_backend

APP_VERSION = "0.1.0"
_MAX_IMAGE_WIDTH_MM = 140


def _scaled_image_flowable(image_bytes: bytes) -> RLImage:
    with PILImage.open(io.BytesIO(image_bytes)) as img:
        width_px, height_px = img.size
    max_width = _MAX_IMAGE_WIDTH_MM * mm
    scale = min(1.0, max_width / width_px) if width_px else 1.0
    return RLImage(io.BytesIO(image_bytes), width=width_px * scale, height=height_px * scale)


def _query_and_plan(db: Session, execution: Execution) -> tuple[str | None, TaskPlanRecord | None]:
    if not execution.task_plan_id:
        return None, None
    task_plan = db.get(TaskPlanRecord, execution.task_plan_id)
    if task_plan is None:
        return None, None
    query = db.get(Query, task_plan.query_id)
    return (query.raw_text if query else None), task_plan


def generate_analysis_pdf(db: Session, execution: Execution) -> bytes:
    result = execution.result_json or {}
    query_text, task_plan = _query_and_plan(db, execution)
    storage = get_storage_backend()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements: list = []

    elements.append(Paragraph("SatQuery AI — Analysis Report", styles["Title"]))
    elements.append(
        Paragraph(
            f"Execution ID: {execution.id} &nbsp;|&nbsp; System version: {APP_VERSION} &nbsp;|&nbsp; "
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 10))

    if query_text:
        elements.append(Paragraph("Query", styles["Heading2"]))
        elements.append(Paragraph(query_text, styles["Normal"]))
        elements.append(Spacer(1, 6))

    elements.append(Paragraph("Task", styles["Heading2"]))
    elements.append(Paragraph(str(result.get("task") or "N/A"), styles["Normal"]))
    elements.append(Spacer(1, 6))

    model_provenance = result.get("model_provenance") or {}
    if model_provenance:
        elements.append(Paragraph("Model", styles["Heading2"]))
        line = f"{model_provenance.get('model_id', 'N/A')} (version {model_provenance.get('version', 'N/A')})"
        if model_provenance.get("demo_mode"):
            line += " — demo/mock model, not a calibrated production model"
        elements.append(Paragraph(line, styles["Normal"]))
        if model_provenance.get("fallback_used"):
            elements.append(Paragraph(f"Fallback used: {model_provenance.get('fallback_reason')}", styles["Normal"]))
        elements.append(Spacer(1, 6))

    data_provenance = result.get("data_provenance") or {}
    if data_provenance:
        elements.append(Paragraph("Data", styles["Heading2"]))
        for label, key in (
            ("Provider", "provider"),
            ("Scene ID", "scene_id"),
            ("Acquisition date", "acquisition_date"),
            ("Sensor", "sensor"),
            ("CRS", "crs"),
            ("Resolution", "resolution"),
            ("Retrieved at", "retrieved_at"),
        ):
            value = data_provenance.get(key)
            if value:
                elements.append(Paragraph(f"{label}: {value}", styles["Normal"]))
        if data_provenance.get("processing_applied"):
            elements.append(
                Paragraph("Processing: " + " → ".join(data_provenance["processing_applied"]), styles["Normal"])
            )
        elements.append(Spacer(1, 6))

    if task_plan and task_plan.location_json:
        elements.append(Paragraph("Location", styles["Heading2"]))
        elements.append(Paragraph(str(task_plan.location_json.get("place_name") or task_plan.location_json), styles["Normal"]))
        elements.append(Spacer(1, 6))

    elements.append(Paragraph("Answer", styles["Heading2"]))
    elements.append(Paragraph(str(result.get("answer") or "N/A"), styles["Normal"]))
    elements.append(Spacer(1, 6))

    confidence = result.get("confidence") or {}
    if confidence:
        elements.append(Paragraph("Confidence", styles["Heading2"]))
        elements.append(
            Paragraph(
                f"Level: {confidence.get('overall_level', 'N/A')} "
                f"({'demo mode, not calibrated' if confidence.get('mode') == 'demo_heuristic' else 'calibrated'})",
                styles["Normal"],
            )
        )
        elements.append(
            Paragraph(
                f"Input quality: {confidence.get('input_quality', 'N/A')} | "
                f"Evidence quality: {confidence.get('evidence_quality', 'N/A')}",
                styles["Normal"],
            )
        )
        if confidence.get("modality_agreement") not in (None, "not_applicable"):
            elements.append(Paragraph(f"Modality agreement: {confidence['modality_agreement']}", styles["Normal"]))
        for note in confidence.get("notes", []):
            elements.append(Paragraph(f"Note: {note}", styles["Normal"]))
        elements.append(Spacer(1, 6))

    evidence_items = result.get("evidence", [])
    if evidence_items:
        elements.append(Paragraph("Evidence", styles["Heading2"]))
        for ev in evidence_items:
            line = ev.get("type", "")
            if ev.get("label"):
                line += f" — {ev['label']}"
            if ev.get("area_m2") is not None:
                line += f" — {ev['area_m2']:,.0f} m² ({ev.get('area_percentage', 0):.2f}%)"
            elif ev.get("area_percentage") is not None:
                line += f" — {ev['area_percentage']:.2f}% of compared pixels (no geographic resolution available)"
            elements.append(Paragraph(line, styles["Normal"]))
            storage_key = ev.get("storage_key")
            if storage_key and storage.exists(storage_key):
                try:
                    elements.append(_scaled_image_flowable(storage.get_bytes(storage_key)))
                except Exception:  # noqa: BLE001 - a broken image must not break the report
                    pass
            elements.append(Spacer(1, 8))

    warnings = result.get("warnings", [])
    if warnings:
        elements.append(Paragraph("Warnings", styles["Heading2"]))
        for w in warnings:
            elements.append(Paragraph(f"• {w}", styles["Normal"]))
        elements.append(Spacer(1, 6))

    elements.append(Paragraph("Execution Summary", styles["Heading2"]))
    elements.append(Paragraph(f"Status: {execution.status}", styles["Normal"]))
    if execution.latency_ms is not None:
        elements.append(Paragraph(f"Latency: {execution.latency_ms} ms", styles["Normal"]))
    created_ts = execution.created_at.isoformat() if execution.created_at else datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    elements.append(Paragraph(f"Timestamp: {created_ts}", styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()
