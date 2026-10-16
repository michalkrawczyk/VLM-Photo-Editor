from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, field

import numpy as np
import structlog
from PIL import Image

from vlm_photo_editor.models.registry import build_client
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.schema.report import StepCheck

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a photo editing quality critic. You will be shown a before image and an after image, \
the editing intent, and (when available) the plan that was applied and deterministic \
measurements of what changed.

Judge three things: intent fidelity (did it do what was asked), naturalness (does it look like \
a believable photograph), and artifacts (halos, banding, clipped areas, jagged edges, colour \
shifts).

Output ONLY valid JSON in this exact format (no other text):
{"verdict": "pass" | "fail" | "uncertain", "reason": "concise explanation", \
"step_id": "id of the plan step most at fault, or null"}

"fail": the edit clearly did not achieve the intent, made the wrong adjustment, made no visible \
change when one was expected, or introduced an obvious artifact.
"uncertain": you genuinely cannot tell from these images. Do not default to "pass"."""


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
    failed_step_ids: list[str] = field(default_factory=list)


def _plan_lines(plan: HumanPlan) -> str:
    rows = [
        f"- step_id {s.step_id}: {s.title} ({', '.join(o.value for o in s.op_names)}) — {s.why}"
        for s in plan.steps
    ]
    head = f"Diagnosis: {plan.diagnosis}\n" if plan.diagnosis else ""
    return head + "\n".join(rows)


def _parse_verdict(data: dict) -> CriticVerdict:
    """Accept the current ``verdict`` format and the legacy ``{"passed": bool}`` one."""
    step = data.get("step_id")
    failed = [str(step)] if step else []
    verdict = data.get("verdict")
    if verdict is None:
        return CriticVerdict(
            passed=bool(data.get("passed", True)), reason=str(data.get("reason", ""))
        )
    reason = str(data.get("reason", ""))
    if verdict == "fail":
        return CriticVerdict(passed=False, reason=reason, failed_step_ids=failed)
    # "uncertain" (or anything unrecognised) is surfaced as inconclusive, never as a silent pass.
    return CriticVerdict(passed=True, reason=reason, uncertain=verdict != "pass")


class Critic:
    def verify(
        self,
        before: np.ndarray,
        after: np.ndarray,
        intent: str,
        plan: HumanPlan | None = None,
        checks: list[StepCheck] | None = None,
    ) -> CriticVerdict:
        """Judge the edit against ``intent``.

        Stage 1 (free, deterministic): ``checks`` come from ``analysis.critic_checks``. Any
        failed check is a fail with the numbers as the reason, and the VLM is not called.
        Stage 2 (VLM): sees before/after plus the plan and the stage-1 measurements.
        """
        failed = [c for c in checks or [] if not c.ok]
        if failed:
            return CriticVerdict(
                passed=False,
                reason="; ".join(c.describe() for c in failed),
                failed_step_ids=[c.step_id for c in failed if c.step_id],
            )

        from langchain_core.messages import HumanMessage, SystemMessage

        before_b64 = _encode_image(before)
        after_b64 = _encode_image(after)

        context = ""
        if plan is not None and plan.steps:
            context += f"\n\nPlan that was applied:\n{_plan_lines(plan)}"
        if checks:
            context += "\n\nMeasured (all passed):\n" + "\n".join(c.describe() for c in checks)
        content = [
            {"type": "text", "text": f'Editing intent: "{intent}"{context}\n\nBefore image:'},
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
            match = re.search(r'\{.*"(?:verdict|passed)".*\}', text, re.DOTALL)
            if not match:
                log.warning("critic.no_json_found", response_preview=text[:200])
                return CriticVerdict(
                    passed=True, reason="parse error — assuming pass", uncertain=True
                )
            return _parse_verdict(json.loads(match.group()))
        except Exception:
            log.warning("critic.failed", exc_info=True)
            return CriticVerdict(passed=True, reason="critic error — assuming pass", uncertain=True)
