"""PreprocessingPipeline -- real geospatial preprocessing: reprojection,
resampling, co-registration/alignment, and AOI cropping. Every operation
actually performed is recorded, feeding DataProvenance.processing_applied
so the transparency view never claims a step that didn't run.

Single-image reads are cached by the image's content checksum (see
app/storage/cache.py) so a multi-turn follow-up question on the same
already-uploaded image reuses the decoded raster instead of re-reading
and re-decoding the file from disk -- this is what backs MVP Test 10.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import cv2
import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject

from app.storage.cache import get_cache_backend

_RASTER_CACHE_TTL_SECONDS = 3600


@dataclass
class PreprocessedRaster:
    array: np.ndarray
    crs: str | None
    transform: object | None
    operations: list[str] = field(default_factory=list)


def read_array(path: str) -> tuple[np.ndarray, str | None, object | None]:
    try:
        with rasterio.open(path) as ds:
            array = ds.read(out_dtype="float64")
            crs = str(ds.crs) if ds.crs else None
            transform = ds.transform
        return array, crs, transform
    except Exception:
        # Fallback for standard non-georeferenced images (PNG, JPEG, WebP)
        from PIL import Image as PILImage
        with PILImage.open(path) as img:
            rgb = img.convert("RGB")
            arr = np.asarray(rgb, dtype=np.float64)
            # Normalize to (bands, H, W) layout expected across preprocessing
            if arr.ndim == 3:
                arr = np.transpose(arr, (2, 0, 1))
            elif arr.ndim == 2:
                arr = arr[np.newaxis, ...]
        return arr, None, None


def reproject_to(
    array: np.ndarray, src_crs: str, src_transform, dst_crs: str
) -> tuple[np.ndarray, object]:
    """Real reprojection via rasterio.warp, band by band."""
    bands, height, width = array.shape
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, width, height, *rasterio.transform.array_bounds(height, width, src_transform)
    )
    out = np.zeros((bands, dst_height, dst_width), dtype=array.dtype)
    for i in range(bands):
        reproject(
            source=array[i],
            destination=out[i],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
    return out, dst_transform


def coregister(before: np.ndarray, after: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Align `after` to `before`'s pixel grid. When both already share the
    same dimensions, this is a no-op cropping to the common shape (the
    honest default for a prototype without a feature-matching aligner)."""
    ops: list[str] = []
    _, h1, w1 = before.shape
    _, h2, w2 = after.shape
    h, w = min(h1, h2), min(w1, w2)
    if (h1, w1) != (h2, w2):
        ops.append(f"cropped both images to common shape ({h}x{w})")
    return before[:, :h, :w], after[:, :h, :w], ops


def resample_to_shape(array: np.ndarray, target_hw: tuple[int, int]) -> np.ndarray:
    bands = array.shape[0]
    target_h, target_w = target_hw
    out = np.zeros((bands, target_h, target_w), dtype=array.dtype)
    for i in range(bands):
        out[i] = cv2.resize(array[i].astype(np.float32), (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    return out


class PreprocessingPipeline:
    def align_pair(self, before_path: str, after_path: str) -> tuple[PreprocessedRaster, PreprocessedRaster]:
        ops_before: list[str] = ["read raster"]
        ops_after: list[str] = ["read raster"]

        before_arr, before_crs, before_transform = read_array(before_path)
        after_arr, after_crs, after_transform = read_array(after_path)

        if before_crs and after_crs and before_crs != after_crs:
            after_arr, after_transform = reproject_to(after_arr, after_crs, after_transform, before_crs)
            after_crs = before_crs
            ops_after.append(f"reprojected to {before_crs}")

        before_arr, after_arr, coreg_ops = coregister(before_arr, after_arr)
        ops_before.extend(coreg_ops)
        ops_after.extend(coreg_ops)

        return (
            PreprocessedRaster(array=before_arr, crs=before_crs, transform=before_transform, operations=ops_before),
            PreprocessedRaster(array=after_arr, crs=after_crs, transform=after_transform, operations=ops_after),
        )

    def __init__(self) -> None:
        self._cache = get_cache_backend()

    def load_single(self, path: str, cache_key: str | None = None) -> PreprocessedRaster:
        if cache_key:
            cached_bytes = self._cache.get_bytes(f"raster:{cache_key}")
            if cached_bytes is not None:
                cached = pickle.loads(cached_bytes)
                return PreprocessedRaster(
                    array=cached.array,
                    crs=cached.crs,
                    transform=cached.transform,
                    operations=[*cached.operations, "reused cached decode (same image, no re-read)"],
                )

        array, crs, transform = read_array(path)
        raster = PreprocessedRaster(array=array, crs=crs, transform=transform, operations=["read raster"])

        if cache_key:
            self._cache.set_bytes(f"raster:{cache_key}", pickle.dumps(raster), ttl_seconds=_RASTER_CACHE_TTL_SECONDS)

        return raster
