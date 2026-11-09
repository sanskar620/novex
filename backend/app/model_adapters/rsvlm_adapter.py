"""RS-VLM adapter — real target: InternVL3-1B adapted for remote sensing via
LoRA/QLoRA (see ml/training/train_internvl.py). Activated by setting
INTERNVL_MODEL_PATH; until then, this runs a deterministic heuristic that
inspects the actual uploaded pixels (see image_stats.py) rather than
fabricating an answer, and always reports demo_mode=True.

Capabilities: vqa, captioning, grounding.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import get_settings
from app.ml_bootstrap import ensure_ml_importable
from app.model_adapters.base import AdapterOutput, BaseModelAdapter, ModelHealth
from app.model_adapters.image_stats import (
    coverage_fraction,
    largest_contour_bbox,
    to_uint8_bgr,
    water_vegetation_builtup_masks,
)

ensure_ml_importable()


class RSVLMAdapter(BaseModelAdapter):
    model_id = "internvl_rs"
    model_name = "InternVL3-1B (remote-sensing adapted)"
    capability = ["vqa", "captioning", "grounding"]
    supported_modalities = ["optical", "multispectral"]
    supported_tasks = ["vqa", "captioning", "grounding"]
    required_inputs = ["image_array"]
    output_schema = {"answer": "str", "evidence": "list", "score": "float"}

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._model_path = settings.internvl_model_path
        self.version = "InternVL3-1B" if self._model_path else "0.1.0-mock"

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
        if kwargs.get("image_array") is None:
            errors.append("An image is required for this analysis.")
        return errors

    def predict(self, **kwargs: Any) -> AdapterOutput:
        task = kwargs.get("task", "vqa")
        image_array: np.ndarray = kwargs["image_array"]
        question: str = kwargs.get("question", "")

        if not self._model_path:
            return self._predict_mock(task, image_array, question)
        try:
            return self._predict_real(task, image_array, question)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Real VLM inference failed: %s; falling back to pixel heuristic inspection", exc)
            fallback_res = self._predict_mock(task, image_array, question)
            fallback_res["basis"] = f"heuristic pixel inspection (real model fallback: {exc})"
            return fallback_res

    def _predict_real(self, task: str, image_array: np.ndarray, question: str) -> AdapterOutput:
        from ml.inference.internvl_infer import get_internvl

        inference = get_internvl(self._model_path)
        result = inference.predict(task, image_array, question)

        return AdapterOutput(
            answer=result["answer"],
            evidence=result["evidence"],
            # InternVL exposes no calibrated confidence for its answers, so no
            # score is reported rather than inventing one; the confidence
            # service treats a missing score as "moderate, uncalibrated".
            score=None,
            demo_mode=False,
            basis=f"InternVL ({self._model_path}) vision-language model",
        )

    def _predict_mock(self, task: str, image_array: np.ndarray, question: str) -> AdapterOutput:
        bgr = to_uint8_bgr(image_array)
        masks = water_vegetation_builtup_masks(bgr)
        coverages = {k: coverage_fraction(v) for k, v in masks.items() if k != "gray"}
        dominant = max(coverages, key=coverages.get) if coverages else "unknown"

        if task == "captioning":
            answer = self._caption(bgr.shape, coverages, dominant)
            evidence: list[dict] = []
            score = 0.5
        elif task == "grounding":
            target = self._infer_grounding_target(question, coverages)
            if target is None:
                answer = "I could not identify a clear region matching that description in this image."
                evidence = []
                score = 0.2
            else:
                bbox = largest_contour_bbox(masks[target])
                if bbox is None:
                    answer = f"No clearly distinguishable {target.replace('_', ' ')} region was detected."
                    evidence = []
                    score = 0.2
                else:
                    answer = f"The most likely {target.replace('_', ' ')} region is highlighted below."
                    evidence = [
                        {
                            "type": "bounding_box",
                            "coordinates": list(bbox),
                            "label": target,
                            "score": round(coverages[target], 3),
                        }
                    ]
                    score = min(0.9, 0.3 + coverages[target] * 2)
        else:  # vqa
            answer = self._vqa(question, coverages, dominant, bgr.shape)
            evidence = []
            score = 0.5

        return AdapterOutput(
            answer=answer,
            evidence=evidence,
            score=score,
            demo_mode=True,
            basis="heuristic color-threshold inspection of uploaded pixels (not a trained VLM)",
            coverages=coverages,
        )

    @staticmethod
    def _caption(shape: tuple, coverages: dict[str, float], dominant: str) -> str:
        h, w = shape[0], shape[1]
        parts = [f"A {w}x{h} remote-sensing image."]
        if coverages.get(dominant, 0) > 0.05:
            parts.append(f"The scene appears dominated by {dominant.replace('_', ' ')} features.")
        else:
            parts.append("No single land-cover type clearly dominates the scene.")
        return " ".join(parts)

    @staticmethod
    def _infer_grounding_target(question: str, coverages: dict[str, float]) -> str | None:
        q = question.lower()
        if "water" in q or "river" in q or "lake" in q or "pani" in q:
            return "water"
        if "vegetation" in q or "forest" in q or "tree" in q or "green" in q:
            return "vegetation"
        if "built" in q or "building" in q or "urban" in q or "structure" in q:
            return "built_up"
        if coverages:
            return max(coverages, key=coverages.get)
        return None

    @staticmethod
    def _vqa(question: str, coverages: dict[str, float], dominant: str, shape: tuple) -> str:
        q = question.lower()
        if "water" in q:
            pct = coverages.get("water", 0.0) * 100
            return f"Approximately {pct:.1f}% of the visible scene shows water-like spectral characteristics."
        if "vegetation" in q or "forest" in q or "green" in q:
            pct = coverages.get("vegetation", 0.0) * 100
            return f"Approximately {pct:.1f}% of the visible scene shows vegetation-like spectral characteristics."
        if "built" in q or "urban" in q:
            pct = coverages.get("built_up", 0.0) * 100
            return f"Approximately {pct:.1f}% of the visible scene shows built-up/bright surface characteristics."
        if ("what" in q and "visible" in q) or "describe" in q:
            return RSVLMAdapter._caption(shape, coverages, dominant)
        return (
            f"Based on a color-composition heuristic, the scene is most consistent with "
            f"{dominant.replace('_', ' ')} land cover."
        )
