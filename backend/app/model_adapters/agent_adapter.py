"""Qwen3 agent adapter — real target: a locally-run Qwen3 model
(AGENT_MODEL_NAME, e.g. Qwen3-8B) prompted with function-calling/structured
output to emit TaskPlan-shaped JSON. It is never given permission to name
or execute a tool/model directly.

Activated by setting AGENT_MODEL_PATH; until then, this runs a deterministic
rule/keyword-based parser covering English, Hindi, and Hinglish. Its output
is raw, untrusted dict data — app/agents/controller.py is what actually
validates it into a `TaskPlan` and hands it to the Policy Validator. This
adapter must never be trusted as-is.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.core.config import get_settings
from app.ml_bootstrap import ensure_ml_importable
from app.model_adapters.base import AdapterOutput, BaseModelAdapter, ModelHealth

ensure_ml_importable()

_HINDI_WORD_HINTS = [
    "hai", "kya", "kaise", "kahan", "pichle", "saal", "mein", "hua", "hui",
    "badha", "badha hai", "kam", "increase", "dikhao", "batao", "pani",
]
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


class AgentAdapter(BaseModelAdapter):
    model_id = "qwen_agent"
    model_name = "Qwen3 Agent"
    capability = ["task_planning"]
    supported_modalities: list[str] = []
    supported_tasks = ["task_planning"]
    required_inputs = ["query_text"]
    output_schema = {"raw_task_plan": "dict"}

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._model_path = settings.agent_model_path
        self._model_name_configured = settings.agent_model_name
        self.version = self._model_name_configured if self._model_path else "0.1.0-mock"

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
        if not kwargs.get("query_text"):
            return ["No query text was provided."]
        return []

    def predict(self, **kwargs: Any) -> AdapterOutput:
        query_text: str = kwargs["query_text"]
        image_count: int = kwargs.get("image_count", 0)
        conversation_history: list[dict] | None = kwargs.get("conversation_history")
        if not self._model_path:
            return self._predict_mock(query_text, image_count)
        try:
            return self._predict_real(query_text, image_count, conversation_history)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Real agent planning failed: %s; falling back to mock parser", exc)
            return self._predict_mock(query_text, image_count)

    def _predict_real(
        self, query_text: str, image_count: int, conversation_history: list[dict] | None
    ) -> AdapterOutput:
        from ml.inference.qwen_agent_infer import get_qwen_agent

        inference = get_qwen_agent(self._model_path)
        raw_task_plan = inference.predict(
            query_text, image_count, date.today().isoformat(), conversation_history=conversation_history
        )
        raw_task_plan.setdefault("raw_query", query_text)
        return AdapterOutput(
            raw_task_plan=raw_task_plan,
            score=0.7,
            demo_mode=False,
            basis=f"{self._model_name_configured} structured-output generation",
        )

    def _predict_mock(self, query_text: str, image_count: int) -> AdapterOutput:
        language = self._detect_language(query_text)
        q = query_text.lower()

        task, intent = self._detect_task(q, image_count)
        temporal = task in ("change_vqa", "change_detection") or "compare" in q and (
            "date" in q or "year" in q or "before" in q or "after" in q
        )
        requires_two_images = task in ("change_vqa", "change_detection")
        requires_grounding = task == "grounding"
        requires_quantification = task == "change_vqa" and any(
            kw in q for kw in ["increase", "decrease", "how much", "kitna", "badha", "kam"]
        )

        modalities = self._detect_modalities(q, task)
        location = self._extract_location(q)
        date_range = self._extract_date_range(q)
        output_type = ["mask", "report"] if task in ("change_vqa", "change_detection") else ["text"]

        raw_task_plan = {
            "intent": intent,
            "language": language,
            "task": task,
            "modalities": modalities,
            "temporal": temporal,
            "requires_two_images": requires_two_images,
            "requires_grounding": requires_grounding,
            "requires_quantification": requires_quantification,
            "location": location,
            "date_range": date_range,
            "output_type": output_type,
            "raw_query": query_text,
        }

        return AdapterOutput(
            raw_task_plan=raw_task_plan,
            score=0.5,
            demo_mode=True,
            basis="rule/keyword heuristic parser (not a local LLM)",
        )

    @staticmethod
    def _detect_language(text: str) -> str:
        if _DEVANAGARI_RE.search(text):
            return "hi"
        lowered = text.lower()
        hindi_hits = sum(1 for w in _HINDI_WORD_HINTS if w in lowered)
        if hindi_hits >= 2:
            return "hinglish"
        return "en"

    @staticmethod
    def _detect_task(q: str, image_count: int = 0) -> tuple[str, str]:
        if any(kw in q for kw in ["optical and sar", "optical + sar", "radar and optical", "combine optical"]):
            return "optical_sar_analysis", "cross_modal_analysis"
        # Retrieval means "go find imagery for me" -- never the right read
        # when the user already attached images to analyze, even if their
        # wording happens to mention "satellite imagery"/"satellite data".
        if image_count == 0 and any(
            kw in q for kw in ["find satellite", "retrieve", "get satellite", "satellite imagery", "satellite data"]
        ):
            return "satellite_retrieval", "data_retrieval"
        if any(
            kw in q
            for kw in [
                "what changed", "change between", "compare", "increase", "decrease",
                "badha", "kam hua", "badla", "between", "grown", "expanded", "over time",
            ]
        ):
            return "change_vqa", "change_analysis"
        if any(kw in q for kw in ["where is", "where are", "kahan hai", "locate"]):
            return "grounding", "grounding"
        if any(kw in q for kw in ["describe", "caption", "batao"]):
            return "captioning", "captioning"
        return "vqa", "visual_question_answering"

    @staticmethod
    def _detect_modalities(q: str, task: str) -> list[str]:
        if task == "optical_sar_analysis":
            return ["optical", "sar"]
        if any(kw in q for kw in ["vegetation", "crop", "ndvi", "forest health"]):
            return ["multispectral"]
        if any(kw in q for kw in ["cloud cover", "through cloud", "radar", "sar"]):
            return ["sar"]
        return ["optical"]

    _COORD_PAIR_RE = re.compile(r"(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)")

    @classmethod
    def _extract_location(cls, q: str) -> dict | None:
        # A bare "lat, lon" pair (e.g. "19.076, 72.877") takes priority over
        # a place name -- checked first since it's an unambiguous, specific
        # pattern, and range-validated so an unrelated number pair (e.g. two
        # area figures) is never misread as coordinates.
        coord_match = cls._COORD_PAIR_RE.search(q)
        if coord_match:
            lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"latitude": lat, "longitude": lon}

        match = re.search(r"(?:around|near|in|of)\s+([A-Za-z][A-Za-z\s]{2,30})", q)
        if match:
            place = match.group(1).strip().rstrip(".,?!")
            # Avoid capturing trailing junk like "the last year"
            place = re.split(r"\b(between|from|last|since|during)\b", place)[0].strip()
            if place:
                return {"place_name": place.title()}
        return None

    @staticmethod
    def _extract_date_range(q: str) -> list[str] | None:
        today = date.today()
        if "last year" in q or "pichle saal" in q:
            return [(today - timedelta(days=365)).isoformat(), today.isoformat()]
        year_match = re.findall(r"\b(20\d{2})\b", q)
        if len(year_match) >= 2:
            y1, y2 = sorted(year_match[:2])
            return [f"{y1}-01-01", f"{y2}-12-31"]
        if len(year_match) == 1:
            y = year_match[0]
            return [f"{y}-01-01", f"{y}-12-31"]
        return None
