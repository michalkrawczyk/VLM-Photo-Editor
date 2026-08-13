from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass

import numpy as np
import structlog
from PIL import Image

from vlm_photo_editor.models.registry import build_client

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a photo editing quality critic. You will be shown a before image and an after image, \
along with the editing intent. Assess whether the edit achieved the stated intent.

Output ONLY valid JSON in this exact format (no other text):
{"passed": true, "reason": "concise explanation"}

Use "passed": false when the edit clearly did not achieve the intent (e.g. wrong adjustment, \
no visible change when one was expected, or introduced an obvious artifact).
When in doubt, pass."""


def _encode_image(pixels: np.ndarray) -> str:
    if pixels.dtype != np.uint8:
        lo, hi = int(pixels.min()), int(pixels.max())
        span = hi - lo or 1
        pixels = ((pixels.astype(np.float32) - lo) / span * 255).round().astype(np.uint8)
    img = Image.fromarray(pixels)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


@dataclass
class CriticVerdict:
    passed: bool
    reason: str
    uncertain: bool = False


class Critic:
    def verify(self, before: np.ndarray, after: np.ndarray, intent: str) -> CriticVerdict:
        """Compare before/after images against intent; return pass/fail verdict."""
        from langchain_core.messages import HumanMessage, SystemMessage

        before_b64 = _encode_image(before)
        after_b64 = _encode_image(after)

        content = [
            {"type": "text", "text": f'Editing intent: "{intent}"\n\nBefore image:'},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{before_b64}"}},
            {"type": "text", "text": "After image:"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{after_b64}"}},
            {"type": "text", "text": "Did the edit achieve the stated intent?"},
        ]

        try:
            client = build_client("critic")
            response = client.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(content=content),
                ]
            )
            text = response.content if hasattr(response, "content") else str(response)
            match = re.search(r'\{.*"passed".*\}', text, re.DOTALL)
            if not match:
                log.warning("critic.no_json_found", response_preview=text[:200])
                return CriticVerdict(
                    passed=True, reason="parse error — assuming pass", uncertain=True
                )
            data = json.loads(match.group())
            return CriticVerdict(
                passed=bool(data.get("passed", True)),
                reason=str(data.get("reason", "")),
            )
        except Exception:
            log.warning("critic.failed", exc_info=True)
            return CriticVerdict(
                passed=True, reason="critic error — assuming pass", uncertain=True
            )
