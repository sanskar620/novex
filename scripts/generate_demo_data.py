"""Generates a small synthetic demo dataset under data/demo/.

These are NOT real satellite scenes -- no copyrighted/proprietary imagery
is bundled, per the project's data policy. Every file here is procedurally
generated with a fixed random seed and a real (if synthetic) CRS/transform,
and is described honestly in data/demo/metadata/manifest.json as
"synthetic_demo" data. This is what MockSatelliteProvider serves in
DEMO_MODE, and what the sample single/temporal/fusion demo assets are for
manual testing.

Run: python scripts/generate_demo_data.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "data" / "demo"

# A real UTM CRS (Zone 43N, covers western/central India) with an
# arbitrary-but-fixed synthetic origin -- not tied to any real place.
CRS = "EPSG:32643"
ORIGIN_X, ORIGIN_Y = 500000.0, 2200000.0
PIXEL_SIZE = 10.0  # meters/pixel, Sentinel-2-like
WIDTH, HEIGHT = 256, 256

RNG = np.random.default_rng(42)


def _transform():
    return from_origin(ORIGIN_X, ORIGIN_Y, PIXEL_SIZE, PIXEL_SIZE)


def _write_geotiff(path: Path, array: np.ndarray, band_descriptions: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bands, height, width = array.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=bands,
        dtype=array.dtype,
        crs=CRS,
        transform=_transform(),
    ) as ds:
        ds.write(array)
        if band_descriptions:
            ds.descriptions = tuple(band_descriptions)


def _base_scene(seed_offset: int) -> np.ndarray:
    rng = np.random.default_rng(42 + seed_offset)
    # Realistic, smooth synthetic land-cover composite:
    # background soil/terrain with subtle natural variation (not harsh noise)
    r = np.full((HEIGHT, WIDTH), 80, dtype=np.uint16)
    g = np.full((HEIGHT, WIDTH), 85, dtype=np.uint16)
    b = np.full((HEIGHT, WIDTH), 80, dtype=np.uint16)

    # water: bottom-left quadrant, deep clean blue
    r[150:230, 20:100] = 30
    g[150:230, 20:100] = 60
    b[150:230, 20:100] = 160

    # vegetation: top-right quadrant, vibrant healthy green
    r[20:100, 150:230] = 35
    g[20:100, 150:230] = 155
    b[20:100, 150:230] = 40

    # built-up: center, bright neutral urban reflection
    r[100:150, 100:150] = 205
    g[100:150, 100:150] = 200
    b[100:150, 100:150] = 195

    return np.stack([r, g, b]).astype(np.uint16)


def generate_single_optical() -> Path:
    array = _base_scene(seed_offset=0)
    path = DEMO_ROOT / "single" / "optical" / "sample_optical.tif"
    _write_geotiff(path, array, ["Red", "Green", "Blue"])
    return path


def generate_single_multispectral() -> Path:
    rng = np.random.default_rng(43)
    rgb = _base_scene(seed_offset=1)
    nir = rng.integers(80, 220, (1, HEIGHT, WIDTH), dtype=np.uint16)
    swir1 = rng.integers(40, 160, (1, HEIGHT, WIDTH), dtype=np.uint16)
    swir2 = rng.integers(30, 140, (1, HEIGHT, WIDTH), dtype=np.uint16)
    array = np.concatenate([rgb, nir, swir1, swir2], axis=0)
    path = DEMO_ROOT / "single" / "multispectral" / "sample_multispectral.tif"
    _write_geotiff(path, array, ["Red", "Green", "Blue", "NIR", "SWIR1", "SWIR2"])
    return path


def generate_single_sar() -> Path:
    # SAR-like speckle: high coefficient of variation, single band --
    # what modality_detector.py's heuristic is designed to catch.
    rng = np.random.default_rng(44)
    base = rng.gamma(shape=1.5, scale=40.0, size=(HEIGHT, WIDTH))
    array = np.clip(base, 0, 255).astype(np.uint16)[np.newaxis, ...]
    path = DEMO_ROOT / "single" / "sar" / "sample_sar.tif"
    _write_geotiff(path, array, ["VV"])
    return path


def generate_temporal_pair() -> tuple[Path, Path]:
    before = _base_scene(seed_offset=2)
    after = before.copy()
    # Simulate built-up expansion: brighten + desaturate a new region.
    after[:, 160:210, 40:110] = np.stack(
        [
            np.full((50, 70), 195, dtype=np.uint16),
            np.full((50, 70), 190, dtype=np.uint16),
            np.full((50, 70), 185, dtype=np.uint16),
        ]
    )
    before_path = DEMO_ROOT / "temporal" / "before" / "sample_before.tif"
    after_path = DEMO_ROOT / "temporal" / "after" / "sample_after.tif"
    _write_geotiff(before_path, before, ["Red", "Green", "Blue"])
    _write_geotiff(after_path, after, ["Red", "Green", "Blue"])
    return before_path, after_path


def generate_fusion_pair() -> tuple[Path, Path]:
    optical = _base_scene(seed_offset=3)
    rng = np.random.default_rng(45)
    sar = rng.gamma(shape=1.5, scale=40.0, size=(HEIGHT, WIDTH))
    # Make the built-up region also high-backscatter in SAR, so the CROMA
    # mock's cross-modal agreement heuristic has something real to agree on.
    sar[100:150, 100:150] = rng.gamma(shape=2.0, scale=90.0, size=(50, 50))
    sar_array = np.clip(sar, 0, 255).astype(np.uint16)[np.newaxis, ...]

    optical_path = DEMO_ROOT / "fusion" / "optical" / "sample_fusion_optical.tif"
    sar_path = DEMO_ROOT / "fusion" / "sar" / "sample_fusion_sar.tif"
    _write_geotiff(optical_path, optical, ["Red", "Green", "Blue"])
    _write_geotiff(sar_path, sar_array, ["VV"])
    return optical_path, sar_path


def _bbox_geojson() -> list[float]:
    minx = ORIGIN_X
    maxy = ORIGIN_Y
    maxx = ORIGIN_X + WIDTH * PIXEL_SIZE
    miny = ORIGIN_Y - HEIGHT * PIXEL_SIZE
    return [minx, miny, maxx, maxy]


def write_manifest(paths: dict[str, Path]) -> None:
    bbox = _bbox_geojson()
    now = datetime(2025, 6, 15, tzinfo=timezone.utc)
    scenes = [
        {
            "scene_id": "demo-optical-001",
            "product_id": "SYNTHETIC-OPTICAL-001",
            "modality": "optical",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": 5.0,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["optical"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-multispectral-001",
            "product_id": "SYNTHETIC-MULTISPECTRAL-001",
            "modality": "multispectral",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": 8.0,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["multispectral"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-sar-001",
            "product_id": "SYNTHETIC-SAR-001",
            "modality": "sar",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": None,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["sar"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-optical-before-001",
            "product_id": "SYNTHETIC-OPTICAL-BEFORE-001",
            "modality": "optical",
            "acquisition_time": datetime(2024, 6, 15, tzinfo=timezone.utc).isoformat(),
            "cloud_percentage": 4.0,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["before"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-optical-after-001",
            "product_id": "SYNTHETIC-OPTICAL-AFTER-001",
            "modality": "optical",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": 6.0,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["after"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-fusion-optical-001",
            "product_id": "SYNTHETIC-FUSION-OPTICAL-001",
            "modality": "optical",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": 5.0,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["fusion_optical"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
        {
            "scene_id": "demo-fusion-sar-001",
            "product_id": "SYNTHETIC-FUSION-SAR-001",
            "modality": "sar",
            "acquisition_time": now.isoformat(),
            "cloud_percentage": None,
            "bbox": bbox,
            "crs": CRS,
            "resolution": PIXEL_SIZE,
            "file_path": str(paths["fusion_sar"].relative_to(REPO_ROOT)).replace("\\", "/"),
        },
    ]

    manifest = {
        "notice": (
            "All scenes in this manifest are SYNTHETIC demo data, procedurally generated "
            "for local development and demonstration. They are not real satellite imagery."
        ),
        "scenes": scenes,
    }
    manifest_path = DEMO_ROOT / "metadata" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def main() -> None:
    optical_path = generate_single_optical()
    multispectral_path = generate_single_multispectral()
    sar_path = generate_single_sar()
    before_path, after_path = generate_temporal_pair()
    fusion_optical_path, fusion_sar_path = generate_fusion_pair()

    write_manifest(
        {
            "optical": optical_path,
            "multispectral": multispectral_path,
            "sar": sar_path,
            "before": before_path,
            "after": after_path,
            "fusion_optical": fusion_optical_path,
            "fusion_sar": fusion_sar_path,
        }
    )
    print("Generated synthetic demo dataset under", DEMO_ROOT)


if __name__ == "__main__":
    main()
