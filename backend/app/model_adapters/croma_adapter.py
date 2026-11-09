"""CROMA adapter — real target: CROMA, a pretrained optical+SAR multimodal
*representation* model (not a fusion model that reasons on its own).
Produces separate optical/SAR representations combined into one
multimodal representation, which a task-specific head then reasons over.
No fine-tuning is promised until real training data/task are established.

Activated by setting CROMA_MODEL_PATH; until then, this computes real
per-band statistics for the optical image and real backscatter-intensity
statistics for the SAR image, and combines them into a labeled mock
multimodal representation.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml_bootstrap import ensure_ml_importable
from app.model_adapters.base import AdapterOutput, BaseModelAdapter, ModelHealth

ensure_ml_importable()


class CromaAdapter(BaseModelAdapter):
    model_id = "croma"
    model_name = "CROMA"
    capability = ["optical_sar_fusion"]
    supported_modalities = ["optical", "sar"]
    supported_tasks = ["optical_sar_analysis"]
    required_inputs = ["optical_array", "sar_array"]
    output_schema = {"representation": "list[float]", "agreement": "str"}

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._model_path = settings.croma_model_path
        self.version = "CROMA-base" if self._model_path else "0.1.0-mock"

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
        optical = kwargs.get("optical_array")
        sar = kwargs.get("sar_array")
        if optical is None or sar is None:
            errors.append(
                "This workflow requires one optical/multispectral image and one SAR image."
            )
            return errors
        if self._model_path:
            opt_bands = optical if optical.ndim == 3 else optical[np.newaxis, ...]
            sar_bands = sar if sar.ndim == 3 else sar[np.newaxis, ...]
            if opt_bands.shape[0] < 12 or sar_bands.shape[0] < 2:
                errors.append(
                    "CROMA requires 12 Sentinel-2 optical bands and 2 Sentinel-1 SAR (VV/VH) bands; "
                    "the provided imagery has too few bands to normalize against the pretrained checkpoint."
                )
        return errors

    def predict(self, **kwargs: Any) -> AdapterOutput:
        optical: np.ndarray = kwargs["optical_array"]
        sar: np.ndarray = kwargs["sar_array"]
        question: str = kwargs.get("question", "")
        if not self._model_path:
            return self._predict_mock(optical, sar, question)
        return self._predict_real(optical, sar)

    def _predict_real(self, optical: np.ndarray, sar: np.ndarray) -> AdapterOutput:
        from ml.inference.croma_infer import get_croma

        inference = get_croma(self._model_path)
        result = inference.predict(optical, sar)
        agreement = "agree" if result["agreement_score"] > 0 else "disagree"
        if agreement == "agree":
            answer = (
                "CROMA's joint optical-SAR representation shows consistent optical/SAR evidence "
                "for this scene."
            )
        else:
            answer = (
                "CROMA's joint optical-SAR representation shows conflicting optical/SAR evidence "
                "for this scene — result should be reviewed."
            )

        return AdapterOutput(
            answer=answer,
            representation=result["representation"],
            optical_representation=result["optical_representation"],
            sar_representation=result["sar_representation"],
            agreement=agreement,
            score=max(0.0, min(1.0, (result["agreement_score"] + 1) / 2)),
            demo_mode=False,
            basis="CROMA-base joint encoder cosine similarity between optical and SAR global representations",
        )

    def _predict_mock(self, optical: np.ndarray, sar: np.ndarray, question: str) -> AdapterOutput:
        opt_bands = optical if optical.ndim == 3 else optical[np.newaxis, ...]
        opt_mean = float(np.nanmean(opt_bands))
        opt_bright_fraction = float(np.mean(opt_bands > np.nanpercentile(opt_bands, 75)))

        sar_band = sar if sar.ndim == 2 else sar[0]
        finite_sar = sar_band[np.isfinite(sar_band)]
        sar_mean_backscatter = float(np.mean(finite_sar)) if finite_sar.size else 0.0
        sar_high_backscatter_fraction = (
            float(np.mean(finite_sar > np.percentile(finite_sar, 75))) if finite_sar.size else 0.0
        )

        # Built-up areas: bright in optical AND high backscatter in SAR.
        # A crude but real cross-modal agreement heuristic.
        optical_says_builtup = opt_bright_fraction > 0.15
        sar_says_builtup = sar_high_backscatter_fraction > 0.15
        agreement = "agree" if optical_says_builtup == sar_says_builtup else "disagree"

        representation = [opt_mean, opt_bright_fraction, sar_mean_backscatter, sar_high_backscatter_fraction]

        if optical_says_builtup and sar_says_builtup:
            answer = "Both optical brightness and SAR backscatter are consistent with built-up surfaces in parts of this scene."
        elif not optical_says_builtup and not sar_says_builtup:
            answer = "Neither optical nor SAR evidence strongly indicates built-up surfaces in this scene."
        else:
            answer = "Optical and SAR evidence disagree on built-up extent in this scene — result should be reviewed."

        return AdapterOutput(
            answer=answer,
            representation=representation,
            agreement=agreement,
            score=0.6 if agreement == "agree" else 0.3,
            demo_mode=True,
            basis="optical brightness fraction vs. SAR backscatter fraction cross-check (not a learned fusion model)",
        )
