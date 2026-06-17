from __future__ import annotations

import base64
import io
import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, SystemMessage

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.models.registry import build_client
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.schema.prefs import Preferences

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer


class Planner:
    def __init__(self, role: str = "planner") -> None:
        self._llm = build_client(role).with_structured_output(HumanPlan)

    def plan(
        self,
        container: "ImageContainer",
        intent: str,
        prefs: Preferences | None = None,
        mode: str = "full",
        composition: str | None = None,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        target_size = (
            frame_target_size(container.width, container.height, composition)
            if composition
            else None
        )
        messages = [
            SystemMessage(content=self._system_prompt(mode, prefs, composition, target_size)),
            HumanMessage(content=self._user_content(container, intent, composition, target_size)),
        ]
        if get_debug_settings().vlm_prompt_debug:
            _log.debug("vlm_prompt system=%s user_text=%s", messages[0].content, intent)
        result = self._llm.invoke(messages)
        result.mode = mode
        return result

    def revise(
        self,
        container: "ImageContainer",
        previous_plan: HumanPlan,
        feedback: str,
        prefs: Preferences | None = None,
        mode: str = "full",
        composition: str | None = None,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        target_size = (
            frame_target_size(container.width, container.height, composition)
            if composition
            else None
        )
        prev_json = previous_plan.model_dump_json(indent=2)
        user_text = (
            f"PREVIOUS PLAN:\n{prev_json}\n\nUSER FEEDBACK: {feedback}\n\n"
            "Revise to incorporate feedback. Keep step_ids stable where step is unchanged."
        )
        messages = [
            SystemMessage(content=self._system_prompt(mode, prefs, composition, target_size)),
            HumanMessage(
                content=self._user_content(container, user_text, composition, target_size)
            ),
        ]
        if get_debug_settings().vlm_prompt_debug:
            _log.debug("vlm_prompt system=%s feedback=%s", messages[0].content, feedback)
        result = self._llm.invoke(messages)
        result.mode = mode
        return result

    def _system_prompt(
        self,
        mode: str,
        prefs: Preferences | None,
        composition: str | None = None,
        target_size: tuple[int, int] | None = None,
    ) -> str:
        allowed = sorted(op.value for op in allowed_ops_for_mode(mode))
        lines = [
            "You are a photo-editing planner. Produce a concise human-readable editing plan.",
            "",
            f"ACTIVE MODE: {mode}",
            f"ALLOWED OPS (use ONLY these): {allowed}",
            "",
            "OUTPUT SCHEMA (HumanPlan — fill all fields):",
            "  plan_id: UUID string",
            "  mode: must equal ACTIVE MODE",
            "  steps: list of HumanStep:",
            "    step_id: UUID string (stable)",
            "    index: 1-based int",
            "    title: ≤8 words",
            "    why: one sentence visual reason",
            "    op_names: list[str] from ALLOWED OPS only",
            "    op_params: list[dict] — one dict per op_name (same order)",
            "",
            "PARAM CONSTRAINTS:",
            "  crop: {left, top, right, bottom} (pixel ints; 0 ≤ left < right ≤ image_width, 0 ≤ top < bottom ≤ image_height)",
            "  rotate: {angle} (float -360 to 360)",
            "  white_balance: {temperature} (float 1000–20000 K)",
            "  exposure: {ev} (float -10 to 10)",
            "  denoise: {}",
            "  mask: {}",
            "  region_edit: {prompt: str}",
            "  background_replace: {prompt: str}",
            "  frame: {mode: str} — one of: rule_of_thirds, golden_ratio, golden_spiral,",
            "    center_symmetry, portrait_headroom, face_only, negative_space,",
            "    fill_frame, lead_room, horizon_third",
            "",
            "RULES:",
            "  - Only ops from ALLOWED OPS. Never invent op names.",
            "  - op_params[i] matches op_names[i]. Lengths must match.",
            "  - ≤5 steps unless strictly necessary.",
            "  - Never include API keys or secrets.",
        ]
        if composition and target_size:
            tw, th = target_size
            lines += [
                "",
                "FRAMING INSTRUCTIONS:",
                f"  Composition: {composition}",
                f"  Target crop: {tw}×{th} px",
                "  - Output exactly one 'crop' step.",
                f"  - Crop must satisfy: right - left == {tw}, bottom - top == {th}.",
                "  - Position the crop to keep the primary subject (face, person, focal point) fully in frame.",
                "  - Follow the composition style when choosing crop position.",
            ]
        if prefs:
            active_explicit = [r.description for r in prefs.explicit if r.active]
            active_learned = [r.description for r in prefs.learned if r.active and r.approved]
            if active_explicit:
                lines += ["", "USER PREFERENCES (highest priority):"]
                lines += [f"  - {d}" for d in active_explicit]
            if active_learned:
                lines += ["", "LEARNED PREFERENCES:"]
                lines += [f"  - {d}" for d in active_learned]
        return "\n".join(lines)

    def _user_content(
        self,
        container: "ImageContainer",
        intent: str,
        composition: str | None = None,
        target_size: tuple[int, int] | None = None,
    ) -> list:
        b64 = self._encode_image(container)
        text = f"Image dimensions: {container.width}x{container.height} pixels\n"
        if composition and target_size:
            tw, th = target_size
            text += f"Target frame: {tw}x{th} px (composition: {composition})\n"
        text += f"Edit intent: {intent}"
        return [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": text},
        ]

    @staticmethod
    def _encode_image(container: "ImageContainer") -> str:
        from PIL import Image

        img = Image.fromarray(container.pixels)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
