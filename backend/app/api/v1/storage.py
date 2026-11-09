from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.storage.object_storage import get_storage_backend

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/{key:path}")
def get_object(key: str) -> Response:
    storage = get_storage_backend()
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="Object not found.")
    data = storage.get_bytes(key)
    lower = key.lower()
    if lower.endswith(".png"):
        content_type = "image/png"
    elif lower.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif lower.endswith(".webp"):
        content_type = "image/webp"
    elif lower.endswith((".tif", ".tiff")):
        content_type = "image/tiff"
    else:
        content_type = "application/octet-stream"
    return Response(content=data, media_type=content_type)
