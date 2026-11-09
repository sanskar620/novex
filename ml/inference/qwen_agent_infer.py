"""Real Qwen3 task-planning inference. Loads a standard `transformers`
checkpoint (no vendored code needed — Qwen3 is a stock causal LM
architecture) and prompts it to emit the exact TaskPlan-shaped JSON that
`app/model_adapters/agent_adapter.py`'s mock path already produces, so
`app/agents/controller.py` validates the output identically either way.

This adapter is loaded at bf16 (~8GB for the 4B checkpoint) to fit
consumer-RAM machines; do not switch to fp32 without checking available
memory (fp32 needs ~16GB for weights alone).
"""
from __future__ import annotations

import json
import re
import threading

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

_lock = threading.Lock()
_cache: dict[str, "QwenAgentInference"] = {}

_SYSTEM_PROMPT = """You are the task-planning component of SatQuery AI, a remote-sensing analysis assistant. \
Given a user's query (in English, Hindi, or Hinglish) and how many images they attached, output ONLY a single \
JSON object (no prose, no markdown fences) with exactly these fields:

{
  "intent": string,
  "language": "en" | "hi" | "hinglish",
  "task": "vqa" | "captioning" | "grounding" | "change_vqa" | "change_detection" | "optical_sar_analysis" | "satellite_retrieval" | "unsupported",
  "modalities": array of "optical" | "multispectral" | "sar",
  "temporal": boolean,
  "requires_two_images": boolean,
  "requires_grounding": boolean,
  "requires_quantification": boolean,
  "location": {"place_name": string} or {"latitude": number, "longitude": number} or null,
  "date_range": [start_ISO_date, end_ISO_date] or null,
  "output_type": array of "text" | "mask" | "report" | "geojson",
  "raw_query": string (the original query, verbatim)
}

Task definitions:
- "vqa": any open question about what's in an attached image (counts, presence/absence, descriptions, "how much of X").
- "grounding": the user wants a SPECIFIC region/object located or highlighted -- typically "where is/are...", "locate...", "point out...". Requires an attached image.
- "captioning": the user wants a general description/summary of an attached image ("describe this", "what is this image of").
- "change_vqa"/"change_detection": comparing two images across time. Require two images -- set requires_two_images true. Use "change_vqa" when the user asks a question about the change; "change_detection" for a bare "detect/show changes" request.
- "optical_sar_analysis": explicitly combining/comparing an optical and a SAR (radar) image together.
- "satellite_retrieval": ONLY when the user has NOT attached any image and is asking you to go find/fetch imagery.
- "unsupported": ONLY for requests that are not about analyzing attached imagery at all -- greetings, small talk, questions about the tool itself, or requests entirely outside remote sensing. If an image is attached and the question is at all about that image, it is NEVER "unsupported" -- classify it as "vqa" at minimum, even if you are not fully sure which specific task fits best.

Examples (input -> key output fields):
- query: "Where is the water?", 1 image attached -> {"task": "grounding", "requires_grounding": true, "modalities": ["optical"]}
- query: "How many buildings are visible?", 1 image attached -> {"task": "vqa", "modalities": ["optical"]}
- query: "Describe this image.", 1 image attached -> {"task": "captioning", "modalities": ["optical"]}
- query: "What changed here?", 2 images attached -> {"task": "change_vqa", "requires_two_images": true}
- query: "Hello, what can you do?", 0 images attached -> {"task": "unsupported"}
- query: "Find imagery of Chennai from last year.", 0 images attached -> {"task": "satellite_retrieval"}
- query: "What's near 19.076, 72.877?", 0 images attached -> {"task": "satellite_retrieval", "location": {"latitude": 19.076, "longitude": 72.877}}

Other rules:
- "requires_grounding" must be true IF AND ONLY IF "task" is "grounding" -- never set requires_grounding true for any other task, and never leave it false when task is "grounding".
- "requires_quantification" is true only for change questions asking "how much"/"by how much"/a percentage.
- If today's date is needed for a relative range like "last year", assume the current date is provided in the query context.
- Earlier turns in this conversation may be included as context. Only reuse a location, date, or image reference from an earlier turn when the CURRENT query is clearly a follow-up that depends on it (e.g. "what about the water there?", "and now?"). A self-contained question that doesn't reference "there"/"it"/"that"/similar must NOT inherit a location or date from earlier turns, even if one was mentioned -- e.g. "where is the water?" after a question about Pune is about the attached image, not about Pune, so location must be null. "raw_query" must be the CURRENT user query only, verbatim -- never the history.
"""


def _resolve_device(device: str | None = None) -> torch.device:
    if device and device != "auto":
        return torch.device(device)
    import os
    env_device = os.environ.get("DEVICE", "").lower()
    if env_device in ("cuda", "cpu"):
        if env_device == "cuda" and not torch.cuda.is_available():
            return torch.device("cpu")
        return torch.device(env_device)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def get_qwen_agent(model_path: str, device: str | None = None) -> "QwenAgentInference":
    dev = _resolve_device(device)
    key = f"{model_path}::{dev}"
    with _lock:
        inst = _cache.get(key)
        if inst is None:
            inst = QwenAgentInference(model_path, device=str(dev))
            inst.load()
            _cache[key] = inst
        return inst


class QwenAgentInference:
    def __init__(self, model_path: str, device: str | None = None):
        self.model_path = model_path
        self.device = _resolve_device(device)
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        )
        self._model.to(self.device)
        self._model.eval()

    @torch.no_grad()
    def predict(
        self,
        query_text: str,
        image_count: int,
        today_iso: str,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("QwenAgentInference.load() must be called before predict()")

        user_content = (
            f"Today's date: {today_iso}\n"
            f"Number of images attached: {image_count}\n"
            f"User query: {query_text}"
        )
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        for turn in conversation_history or []:
            role = "user" if turn.get("role") == "user" else "assistant"
            content = turn.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)

        raw_text = self._generate(inputs)
        parsed = self._extract_json(raw_text)
        if parsed is not None:
            return parsed

        # One retry with an explicit correction nudge before giving up.
        messages.append({"role": "assistant", "content": raw_text})
        messages.append({"role": "user", "content": "That was not valid JSON. Output ONLY the JSON object, nothing else."})
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self.device)
        raw_text = self._generate(inputs)
        parsed = self._extract_json(raw_text)
        if parsed is None:
            raise ValueError(f"Qwen3 agent did not produce valid TaskPlan JSON after retry: {raw_text!r}")
        return parsed

    def _generate(self, inputs) -> str:
        output_ids = self._model.generate(
            **inputs,
            max_new_tokens=400,
            do_sample=False,
            temperature=None,
            top_p=None,
            top_k=None,
        )
        new_tokens = output_ids[0][inputs["input_ids"].shape[-1]:]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
