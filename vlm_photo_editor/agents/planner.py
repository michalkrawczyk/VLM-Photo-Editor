from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from vlm_photo_editor.models.registry import build_client
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.schema.prefs import Preferences
from vlm_photo_editor.templates.planner import build_system_prompt

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer

# AGT-D2: structlog (not stdlib logging) so VLM prompt logs pass the RedactionProcessor.
log = structlog.get_logger()

_NO_TARGET_MODES = {FramingMode.RECOMMEND_BEST, FramingMode.CUSTOM, FramingMode.FILL_FRAME}


class Planner:
    def __init__(self, role: str = "planner") -> None:
        from vlm_photo_editor.config.registry import get_registry

        client = build_client(role)
        # OpenAI strict json_schema rejects HumanPlan's free-form op_params; reasoning
        # models also refuse function tools on /v1/chat/completions. function_calling +
        # (per-entry) reasoning_effort="none" or use_responses_api makes the OpenAI path work.
        if get_registry().get_entry(role).provider == "openai":
            self._llm = client.with_structured_output(HumanPlan, method="function_calling")
        else:
            self._llm = client.with_structured_output(HumanPlan)

    def plan(
        self,
        container: "ImageContainer",
        intent: str,
        prefs: Preferences | None = None,
        mode: str = "full",
        framing_intent: FramingIntent | None = None,
        detected_subject: DetectedSubject | None = None,
        genai_available: bool = True,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        composition, target_size = self._derive_composition(
            framing_intent, container.width, container.height, frame_target_size
        )
        messages = [
            SystemMessage(
                content=build_system_prompt(
                    mode, prefs, framing_intent, target_size, detected_subject, genai_available
                )
            ),
            HumanMessage(
                content=self._user_content(
                    container, intent, composition, target_size, detected_subject
                )
            ),
        ]
        if get_debug_settings().vlm_prompt_debug:
            log.debug("vlm_prompt", system=messages[0].content, user_text=intent)
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
        framing_intent: FramingIntent | None = None,
        detected_subject: DetectedSubject | None = None,
        genai_available: bool = True,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        composition, target_size = self._derive_composition(
            framing_intent, container.width, container.height, frame_target_size
        )
        prev_json = previous_plan.model_dump_json(indent=2)
        user_text = (
            f"PREVIOUS PLAN:\n{prev_json}\n\nUSER FEEDBACK: {feedback}\n\n"
            "Revise to incorporate feedback. Keep step_ids stable where step is unchanged."
        )
        messages = [
            SystemMessage(
                content=build_system_prompt(
                    mode, prefs, framing_intent, target_size, detected_subject, genai_available
                )
            ),
            HumanMessage(
                content=self._user_content(
                    container, user_text, composition, target_size, detected_subject
                )
            ),
        ]
        if get_debug_settings().vlm_prompt_debug:
            log.debug("vlm_prompt", system=messages[0].content, feedback=feedback)
        result = self._llm.invoke(messages)
        result.mode = mode
        return result

    @staticmethod
    def _derive_composition(
        framing_intent: FramingIntent | None,
        width: int,
        height: int,
        frame_target_size_fn,
    ) -> tuple[str | None, tuple[int, int] | None]:
        if framing_intent is None or framing_intent.mode in _NO_TARGET_MODES:
            return None, None
        composition = framing_intent.mode.value
        target_size = frame_target_size_fn(width, height, composition)
        return composition, target_size

    def _user_content(
        self,
        container: "ImageContainer",
        intent: str,
        composition: str | None = None,
        target_size: tuple[int, int] | None = None,
        detected_subject: DetectedSubject | None = None,
    ) -> list:
        b64 = self._encode_image(container)
        text = f"Image dimensions: {container.width}x{container.height} pixels\n"
        if composition and target_size:
            tw, th = target_size
            text += f"Target frame: {tw}x{th} px (composition: {composition})\n"
        if detected_subject is not None:
            b = detected_subject.bbox
            text += (
                f"Detected subject: {detected_subject.label} "
                f"bbox=({b.x},{b.y},{b.width},{b.height}) "
                f"confidence={detected_subject.confidence:.2f}\n"
            )
        text += f"Edit intent: {intent}"
        return [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": text},
        ]

    @staticmethod
    def _encode_image(container: "ImageContainer") -> str:
        import numpy as np
        from PIL import Image

        pixels = container.pixels
        if pixels.dtype != np.uint8:
            lo, hi = int(pixels.min()), int(pixels.max())
            span = hi - lo or 1
            pixels = ((pixels.astype(np.float32) - lo) / span * 255).round().astype(np.uint8)
        img = Image.fromarray(pixels)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
