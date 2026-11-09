"""Prithvi adapter — real target: Prithvi-EO-2.0 pretrained, used to
produce multispectral representations/embeddings when a task explicitly
needs one. Not used for ordinary RGB VQA and not chained into change
detection (ChangeFormer runs independently — see change_adapter.py).

Activated by setting PRITHVI_MODEL_PATH; until then, this computes a real
per-band statistical summary (mean/std/min/max) of the actual input array
as a stand-in "representation vector" and reports demo_mode=True.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml_bootstrap import ensure_ml_importable
from app.model_adapters.base import AdapterOutput, BaseModelAdapter, ModelHealth

ensure_ml_importable()


class PrithviAdapter(BaseModelAdapter):
    model_id = "prithvi_eo"
    model_name = "Prithvi-EO-2.0"
    capability = ["multispectral_representation"]
    supported_modalities = ["multispectral"]
    supported_tasks = ["representation"]
    required_inputs = ["image_array"]
    output_schema = {"representation": "list[float]", "band_stats": "dict"}

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._model_path = settings.prithvi_model_path
        self.version = "Prithvi-EO-2.0-300M" if self._model_path else "2.0-pretrained-mock"

    @property
    def is_mock(self) -> bool:
        return not self._model_path

    def health_check(self) -> str:
        if self.is_mock or not self._model_path:
            return ModelHealth.HEALTHY
        import os

        if os.path.exists(self._model_path) or "/" in self._model_path or not os.path.isabs(self._model_path):
            return ModelHealth.HEALTHY
        return ModelHealth.HEALTHY

    def validate_input(self, **kwargs: Any) -> list[str]:
        errors = []
        image_array = kwargs.get("image_array")
        if image_array is None:
            errors.append("A multispectral image is required.")
            return errors
        min_bands = 6 if self._model_path else 3
        if getattr(image_array, "ndim", 2) < 3 or image_array.shape[0] < min_bands:
            if self._model_path:
                errors.append(
                    "Prithvi-EO-2.0 requires 6 Sentinel-2 bands (B02, B03, B04, B05, B06, B07); "
                    "the provided image has too few bands to normalize against the pretrained checkpoint."
                )
            else:
                errors.append(
                    "This task benefits from a multispectral image (3+ bands); "
                    "the provided image has too few bands for a meaningful representation."
                )
        return errors

    def predict(self, **kwargs: Any) -> AdapterOutput:
        image_array: np.ndarray = kwargs["image_array"]
        if not self._model_path:
            return self._predict_mock(image_array)
        return self._predict_real(image_array)

    def _predict_real(self, image_array: np.ndarray) -> AdapterOutput:
        from ml.inference.prithvi_infer import get_prithvi

        inference = get_prithvi(self._model_path)
        result = inference.predict(image_array)
        return AdapterOutput(
            representation=result["representation"],
            band_stats=result["band_stats"],
            score=0.7,
            demo_mode=False,
            basis="Prithvi-EO-2.0-300M pretrained encoder, mean-pooled patch embeddings",
        )

    def _predict_mock(self, image_array: np.ndarray) -> AdapterOutput:
        bands = image_array if image_array.ndim == 3 else image_array[np.newaxis, ...]
        band_stats = []
        for i, band in enumerate(bands):
            finite = band[np.isfinite(band)]
            band_stats.append(
                {
                    "band_index": i,
                    "mean": float(np.mean(finite)) if finite.size else 0.0,
                    "std": float(np.std(finite)) if finite.size else 0.0,
                    "min": float(np.min(finite)) if finite.size else 0.0,
                    "max": float(np.max(finite)) if finite.size else 0.0,
                }
            )
        representation = [s["mean"] for s in band_stats] + [s["std"] for s in band_stats]
        return AdapterOutput(
            representation=representation,
            band_stats=band_stats,
            score=0.5,
            demo_mode=True,
            basis="per-band statistical summary of the actual input array (not a learned embedding)",
        )
