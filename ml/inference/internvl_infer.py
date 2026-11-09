"""Real InternVL3 inference for VQA, captioning and grounding.

Loads a plain `InternVLChatModel` checkpoint via `trust_remote_code`. If your
checkpoint came straight out of a LoRA training run, convert it first --
`python -m ml.inference.convert_internvl_peft` -- otherwise every language-model
tensor loads as randomly-initialized garbage (see that script's docstring).

Grounding uses InternVL's native referring-expression format, which returns
`<box>[[x1, y1, x2, y2]]</box>` in 0-1000 normalized coordinates; those are
rescaled here to pixel coordinates of the original image.

Runs at float32 (~3.8GB for the 1B checkpoint). The task-planning Qwen3 model
is resident at the same time, so on a 16GB machine keep an eye on memory; drop
this to bfloat16 if you hit pressure.
"""
from __future__ import annotations

import re
import threading

import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image

_IMAGE_SIZE = 448
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)

# InternVL emits boxes on a fixed 0-1000 grid regardless of input resolution.
_BOX_GRID = 1000.0

# Grounding takes a referring expression ("water"), not a question ("where is
# the water"). Passing the raw question makes the model ground the phrase
# literally and drift onto captions/legends, so the interrogative framing is
# stripped first. Verified: "where is the water" boxed an image legend, while
# "water" boxed the actual water.
_LEADING_QUESTION_RE = re.compile(
    r"^\s*(?:"
    r"where(?:'s| is| are)?|"
    r"can you\s+(?:show|find|locate|point out|highlight|identify|detect)(?:\s+me)?|"
    r"(?:please\s+)?(?:show me|find|locate|point out|highlight|identify|detect)"
    r")\b[\s,]*(?:the\s+|a\s+|an\s+)?",
    re.IGNORECASE,
)
_TRAILING_CONTEXT_RE = re.compile(
    r"[\s,]*(?:"
    r"in\s+(?:this|the)\s+(?:image|picture|photo|scene|imagery)|"
    r"kahan\s+(?:hai|hain|h|he)"  # Hinglish: "pani kahan hai" -> "pani"
    r")\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def _referring_phrase(question: str) -> str:
    """Reduce a user question to the noun phrase InternVL should ground."""
    text = _TRAILING_CONTEXT_RE.sub("", question.strip())
    text = _LEADING_QUESTION_RE.sub("", text)
    text = text.strip(" ?.!,")
    if text:
        return text
    # Stripping consumed everything (e.g. a bare "where?") -- fall back to the
    # original wording rather than silently grounding nothing.
    return question.strip(" ?.!,") or "the main object"
# The reply may or may not wrap the box in <box></box> -- this checkpoint answers
# bare, e.g. `the river[[500, 507, 999, 743]]` -- so match the [[...]] payload
# itself and treat the tags as optional.
_BOX_RE = re.compile(r"\[\[\s*([-\d\s.,]+?)\s*\]\]", re.DOTALL)

_lock = threading.Lock()
_cache: dict[str, "InternVLInference"] = {}


def get_internvl(model_path: str) -> "InternVLInference":
    with _lock:
        inst = _cache.get(model_path)
        if inst is None:
            inst = InternVLInference(model_path)
            inst.load()
            _cache[model_path] = inst
        return inst


def _to_pil(image_array: np.ndarray) -> Image.Image:
    """(bands, H, W) or (H, W) raster -> contrast-stretched RGB PIL image."""
    arr = image_array
    if arr.ndim == 2:
        bands = np.stack([arr] * 3, axis=0)
    elif arr.shape[0] >= 3:
        bands = arr[:3]
    else:
        bands = np.repeat(arr[:1], 3, axis=0)

    bands = bands.astype(np.float32)
    finite = bands[np.isfinite(bands)]
    if finite.size == 0:
        bands = np.zeros_like(bands)
    else:
        lo, hi = np.percentile(finite, [2, 98])
        if hi <= lo:
            hi = lo + 1.0
        bands = np.clip((bands - lo) / (hi - lo) * 255.0, 0, 255)
    rgb = np.transpose(np.nan_to_num(bands).astype(np.uint8), (1, 2, 0))
    return Image.fromarray(rgb).convert("RGB")


class InternVLInference:
    def __init__(self, model_path: str, device: str = "cpu"):
        self.model_path = model_path
        self.device = torch.device(device)
        self._model = None
        self._tokenizer = None
        self._transform = T.Compose(
            [T.ToTensor(), T.Normalize(_IMAGENET_MEAN, _IMAGENET_STD)]
        )

    def load(self) -> None:
        import torch.nn as nn
        if not hasattr(nn.Module, "all_tied_weights_keys"):
            nn.Module.all_tied_weights_keys = property(lambda self: {})

        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, trust_remote_code=True, use_fast=False
        )
        torch_dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self._model = AutoModel.from_pretrained(
            self.model_path,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
            use_flash_attn=False,
        ).eval()
        self._model.to(self.device)

    def _pixel_values(self, pil: Image.Image) -> torch.Tensor:
        resized = pil.resize((_IMAGE_SIZE, _IMAGE_SIZE))
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        return self._transform(resized).unsqueeze(0).to(device=self.device, dtype=dtype)

    @torch.no_grad()
    def _chat(self, pixel_values: torch.Tensor, prompt: str, max_new_tokens: int) -> str:
        return self._model.chat(
            self._tokenizer,
            pixel_values,
            prompt,
            dict(max_new_tokens=max_new_tokens, do_sample=False),
        ).strip()

    def predict(self, task: str, image_array: np.ndarray, question: str = "") -> dict:
        if self._model is None:
            raise RuntimeError("InternVLInference.load() must be called before predict()")

        pil = _to_pil(image_array)
        height, width = pil.height, pil.width
        pixel_values = self._pixel_values(pil)

        if task == "captioning":
            answer = self._chat(
                pixel_values,
                "<image>\nDescribe this remote-sensing image in detail.",
                max_new_tokens=256,
            )
            return {"answer": answer, "evidence": []}

        if task == "grounding":
            target = _referring_phrase(question) if question.strip() else "the main object"
            raw = self._chat(
                pixel_values,
                "<image>\nPlease provide the bounding box coordinate of the region this "
                f"sentence describes: <ref>{target}</ref>",
                max_new_tokens=64,
            )
            bbox = self._parse_box(raw, width, height)
            if bbox is None:
                return {
                    "answer": (
                        f"No region matching \"{target}\" was located in this image."
                    ),
                    "evidence": [],
                }
            return {
                "answer": f"The region matching \"{target}\" is highlighted below.",
                "evidence": [
                    {
                        "type": "bounding_box",
                        "coordinates": list(bbox),
                        "label": target,
                        # InternVL returns no calibrated confidence for a box, and
                        # inventing one would be a fabricated number. Left unset.
                        "score": None,
                    }
                ],
            }

        prompt = question.strip() or "What is shown in this image?"
        answer = self._chat(pixel_values, f"<image>\n{prompt}", max_new_tokens=256)
        return {"answer": answer, "evidence": []}

    @staticmethod
    def _parse_box(raw: str, width: int, height: int) -> tuple[int, int, int, int] | None:
        match = _BOX_RE.search(raw)
        if not match:
            return None
        try:
            nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", match.group(1))[:4]]
        except ValueError:
            return None
        if len(nums) != 4:
            return None

        x1, y1, x2, y2 = nums
        x1 = int(round(x1 / _BOX_GRID * width))
        x2 = int(round(x2 / _BOX_GRID * width))
        y1 = int(round(y1 / _BOX_GRID * height))
        y2 = int(round(y2 / _BOX_GRID * height))

        x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
        y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)
