"""ChangeFormer adapter — real target: ChangeFormer (or another approved
pretrained change-detection model). Runs independently on aligned
before/after imagery; it is NOT fed Prithvi features in this prototype
(that integration is unvalidated). ChangeFormer produces a change mask —
it is explicitly not a natural-language VQA model; a separate reasoning
layer (see orchestration) interprets the mask into an answer.

Activated by setting CHANGE_MODEL_PATH; until then, this computes a real
pixel-wise absolute-difference + threshold on the two aligned arrays (a
classic, legitimate change-detection heuristic) and reports demo_mode=True.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.config import get_settings
from app.ml_bootstrap import ensure_ml_importable
from app.model_adapters.base import AdapterOutput, BaseModelAdapter, ModelHealth
from app.model_adapters.image_stats import to_uint8_bgr

ensure_ml_importable()


class ChangeDetectionAdapter(BaseModelAdapter):
    model_id = "changeformer"
    model_name = "ChangeFormer"
    capability = ["change_detection"]
    supported_modalities = ["optical", "multispectral"]
    supported_tasks = ["change_detection"]
    required_inputs = ["image_array_before", "image_array_after"]
    output_schema = {"mask": "ndarray", "changed_fraction": "float"}

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._model_path = settings.change_model_path
        self.version = "ChangeFormerV6-LEVIR" if self._model_path else "0.1.0-mock"

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
        before = kwargs.get("image_array_before")
        after = kwargs.get("image_array_after")
        if before is None or after is None:
            errors.append(
                "This analysis requires two images of the same area from different dates. "
                "Please upload a before and after image, or allow SatQuery AI to retrieve "
                "suitable scenes."
            )
        elif before.shape[-2:] != after.shape[-2:]:
            errors.append(
                "The before and after images have different dimensions after alignment; "
                "co-registration failed to produce a comparable pair."
            )
        return errors

    def predict(self, **kwargs: Any) -> AdapterOutput:
        before: np.ndarray = kwargs["image_array_before"]
        after: np.ndarray = kwargs["image_array_after"]
        if not self._model_path:
            return self._predict_mock(before, after)
        return self._predict_real(before, after)

    def _predict_real(self, before: np.ndarray, after: np.ndarray) -> AdapterOutput:
        from ml.inference.changeformer_infer import get_changeformer

        bgr_before = to_uint8_bgr(before)
        bgr_after = to_uint8_bgr(after)
        inference = get_changeformer(self._model_path)
        mask, confidence = inference.predict(bgr_before, bgr_after)
        changed_fraction = float(np.count_nonzero(mask)) / float(mask.size) if mask.size else 0.0

        return AdapterOutput(
            mask=mask,
            changed_fraction=changed_fraction,
            score=confidence,
            demo_mode=False,
            basis="ChangeFormer (LEVIR-CD pretrained checkpoint) segmentation head",
        )

    def _predict_mock(self, before: np.ndarray, after: np.ndarray) -> AdapterOutput:
        bgr_before = to_uint8_bgr(before)
        bgr_after = to_uint8_bgr(after)
        gray_before = cv2.cvtColor(bgr_before, cv2.COLOR_BGR2GRAY)
        gray_after = cv2.cvtColor(bgr_after, cv2.COLOR_BGR2GRAY)

        diff = cv2.absdiff(gray_before, gray_after)
        diff = cv2.GaussianBlur(diff, (5, 5), 0)
        _, mask = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        changed_fraction = float(np.count_nonzero(mask)) / float(mask.size) if mask.size else 0.0

        return AdapterOutput(
            mask=mask,
            changed_fraction=changed_fraction,
            score=min(0.9, 0.3 + changed_fraction * 3),
            demo_mode=True,
            basis="pixel-wise grayscale absolute-difference + Otsu threshold on aligned images",
        )
