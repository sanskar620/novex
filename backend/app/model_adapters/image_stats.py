"""Shared, real (non-fabricated) pixel-level heuristics used by the mock
adapters. These run actual color-threshold / differencing logic on the
actual uploaded pixels -- they are not deep remote-sensing models, but they
are not fabricated either: every number here is computed from the image
that was actually provided.
"""
from __future__ import annotations

import cv2
import numpy as np


def to_uint8_bgr(array: np.ndarray) -> np.ndarray:
    """Normalize an arbitrary-band raster array to a displayable 3-channel
    uint8 BGR image for evidence rendering and heuristics.
    Correctly handles both channel-first (bands, H, W) and channel-last (H, W, bands)
    and avoids contrast blowout on standard 8-bit images."""
    if array.ndim == 2:
        bands = np.stack([array] * 3, axis=-1)
    elif array.ndim == 3:
        # Detect channel position:
        # If axis 0 is small (1-13 bands) and axis 1/2 are image spatial dimensions, it's (bands, H, W)
        if array.shape[0] in (1, 2, 3, 4, 6, 8, 12, 13) and array.shape[0] < min(array.shape[1], array.shape[2]):
            if array.shape[0] >= 3:
                bands = np.transpose(array[:3], (1, 2, 0))
            else:
                single = array[0]
                bands = np.stack([single] * 3, axis=-1)
        # If axis 2 is 1, 3, or 4 (standard HWC image), keep channels last
        elif array.shape[2] in (1, 3, 4):
            if array.shape[2] >= 3:
                bands = array[..., :3]
            else:
                bands = np.repeat(array[..., :1], 3, axis=-1)
        else:
            bands = np.transpose(array[:3], (1, 2, 0))
    else:
        bands = array

    bands = bands.astype(np.float32)
    finite = bands[np.isfinite(bands)]
    if finite.size == 0:
        return np.zeros((*bands.shape[:2], 3), dtype=np.uint8)

    max_val = float(np.max(finite))
    min_val = float(np.min(finite))

    # Standard 8-bit RGB image: keep original pixels without washing out or distorting
    if max_val <= 255.0 and min_val >= 0.0 and max_val > 1.0:
        scaled = np.clip(bands, 0, 255).astype(np.uint8)
    elif max_val <= 1.0 and min_val >= 0.0:
        scaled = np.clip(bands * 255.0, 0, 255).astype(np.uint8)
    else:
        # High-bit depth satellite raster (12-bit, 16-bit, raw DN): apply 2-98% percentile stretch
        lo, hi = np.percentile(finite, [2, 98])
        if hi <= lo:
            hi = lo + 1.0
        scaled = np.clip((bands - lo) / (hi - lo) * 255.0, 0, 255)
        scaled = np.nan_to_num(scaled).astype(np.uint8)

    return cv2.cvtColor(scaled, cv2.COLOR_RGB2BGR)


def water_vegetation_builtup_masks(bgr: np.ndarray) -> dict[str, np.ndarray]:
    """Simple HSV-threshold heuristic segmentation. Real thresholding on
    real pixels -- a stand-in for a learned segmentation head, not a
    fabricated result."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    water = ((h >= 90) & (h <= 130) & (s > 40)).astype(np.uint8) * 255
    vegetation = ((h >= 35) & (h <= 85) & (s > 40)).astype(np.uint8) * 255
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    builtup = ((s < 60) & (v > 90)).astype(np.uint8) * 255

    return {"water": water, "vegetation": vegetation, "built_up": builtup, "gray": gray}


def largest_contour_bbox(mask: np.ndarray, min_area: int = 50) -> tuple[int, int, int, int] | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_area:
        return None
    x, y, w, h = cv2.boundingRect(largest)
    return (int(x), int(y), int(x + w), int(y + h))


def coverage_fraction(mask: np.ndarray) -> float:
    return float(np.count_nonzero(mask)) / float(mask.size) if mask.size else 0.0
