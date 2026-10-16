from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from vlm_photo_editor.models.registry import build_client
from vlm_photo_editor.planner.repair import plans_equivalent
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.schema.prefs import Preferences
from vlm_photo_editor.schema.report import ImageReport
from vlm_photo_editor.templates.planner import (
    adaptation_rule_lines,
    build_system_prompt,
    measurement_lines,
    revision_rule_lines,
)

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer

# AGT-D2: structlog (not stdlib logging) so VLM prompt logs pass the RedactionProcessor.
log = structlog.get_logger()

# Longest edge sent to the VLM. Providers resize anyway; this caps payload and latency.
_VLM_MAX_EDGE = 1568
_NO_TARGET_MODES = {FramingMode.RECOMMEND_BEST, FramingMode.CUSTOM, FramingMode.FILL_FRAME}

_UNCHANGED_PLAN_NOTE = (
    "Your previous answer was identical to the PREVIOUS PLAN, so the feedback was not applied. "
    "Return a plan whose steps or parameters actually change to satisfy the USER FEEDBACK."
)


def _revision_text(previous_plan: HumanPlan, feedback: str, original_intent: str | None) -> str:
    parts = []
    if original_intent:
        parts.append(f"ORIGINAL USER INSTRUCTION:\n{original_intent}")
    parts.append(f"PREVIOUS PLAN:\n{previous_plan.model_dump_json(indent=2)}")
    parts.append(f"USER FEEDBACK:\n{feedback}")
    parts.append(
        "TASK: Adjust the previous plan so it satisfies the USER FEEDBACK. The feedback takes "
        "priority over the original instruction. Change or remove any step that contradicts it; "
        "keep step_ids stable for steps that stay unchanged. Return the full revised plan."
    )
    return "\n\n".join(parts)


def _adaptation_text(reference_plan: HumanPlan, intent: str) -> str:
    parts = []
    if intent:
        parts.append(f"ORIGINAL USER INSTRUCTION:\n{intent}")
    parts.append(
        "REFERENCE PLAN (approved on a different image):\n"
        f"{reference_plan.model_dump_json(indent=2)}"
    )
    parts.append(
        "TASK: Produce a plan for THIS image that follows the same methodology and intent as the "
        "reference plan. Re-derive every parameter from this image's own measurements and "
        "geometry instead of copying the reference numbers. You may drop, add or reorder steps "
        "when this image needs it. Use fresh UUID step_ids."
    )
    return "\n\n".join(parts)


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
        image_report: ImageReport | None = None,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        composition, target_size = self._derive_composition(
            framing_intent, container.width, container.height, frame_target_size
        )
        messages = [
            SystemMessage(
                content=build_system_prompt(
                    mode,
                    prefs,
                    framing_intent,
                    target_size,
                    detected_subject,
                    genai_available,
                    image_report,
                )
            ),
            HumanMessage(
                content=self._user_content(
                    container, intent, composition, target_size, detected_subject, image_report
                )
            ),
        ]
        if get_debug_settings().vlm_prompt_debug:
            log.debug("vlm_prompt", system=messages[0].content, user_text=intent)
        result = self._llm.invoke(messages)
        result.mode = mode
        return result

    def adapt(
        self,
        container: "ImageContainer",
        reference_plan: HumanPlan,
        intent: str,
        prefs: Preferences | None = None,
        mode: str = "full",
        framing_intent: FramingIntent | None = None,
        detected_subject: DetectedSubject | None = None,
        genai_available: bool = True,
        image_report: ImageReport | None = None,
    ) -> HumanPlan:
        """Plan THIS image following a plan the user approved on another image (batch Mode A)."""
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        composition, target_size = self._derive_composition(
            framing_intent, container.width, container.height, frame_target_size
        )
        system = (
            build_system_prompt(
                mode,
                prefs,
                framing_intent,
                target_size,
                detected_subject,
                genai_available,
                image_report,
            )
            + "\n"
            + "\n".join(adaptation_rule_lines())
        )
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=self._user_content(
                    container,
                    _adaptation_text(reference_plan, intent),
                    composition,
                    target_size,
                    detected_subject,
                    image_report,
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
        image_report: ImageReport | None = None,
        original_intent: str | None = None,
    ) -> HumanPlan:
        from vlm_photo_editor.config.settings import get_debug_settings
        from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

        composition, target_size = self._derive_composition(
            framing_intent, container.width, container.height, frame_target_size
        )
        system = (
            build_system_prompt(
                mode,
                prefs,
                framing_intent,
                target_size,
                detected_subject,
                genai_available,
                image_report,
            )
            + "\n"
            + "\n".join(revision_rule_lines())
        )
        user_text = _revision_text(previous_plan, feedback, original_intent)
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content=self._user_content(
                    container, user_text, composition, target_size, detected_subject, image_report
                )
            ),
        ]
        if get_debug_settings().vlm_prompt_debug:
            log.debug("vlm_prompt", system=messages[0].content, feedback=feedback)
        result = self._llm.invoke(messages)
        if plans_equivalent(previous_plan, result):
            # The model echoed the old plan: ask once more, explicitly.
            log.warning("planner.revise_unchanged_plan")
            messages[1] = HumanMessage(
                content=self._user_content(
                    container,
                    user_text + "\n\n" + _UNCHANGED_PLAN_NOTE,
                    composition,
                    target_size,
                    detected_subject,
                    image_report,
                )
            )
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
        image_report: ImageReport | None = None,
    ) -> list:
        b64 = self._encode_image(container)
        text = f"Image dimensions: {container.width}x{container.height} pixels\n"
        pixel_h, pixel_w = container.pixels.shape[:2]
        sent = self._sent_size(pixel_w, pixel_h)
        if sent != (pixel_w, pixel_h):
            text += (
                f"Image sent to you: {sent[0]}x{sent[1]} (downscaled from the original). "
                f"ALL coordinates you output must be in ORIGINAL pixel space "
                f"(0..{container.width} x 0..{container.height}), not in the downscaled image.\n"
            )
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
        if image_report is not None:
            text += "\n".join(measurement_lines(image_report)) + "\n"
        text += f"Edit intent: {intent}"
        return [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": text},
        ]

    @staticmethod
    def _sent_size(width: int, height: int) -> tuple[int, int]:
        """Pixel size of the image actually sent to the VLM (long edge capped)."""
        scale = _VLM_MAX_EDGE / max(width, height)
        if scale >= 1.0:
            return width, height
        return max(1, round(width * scale)), max(1, round(height * scale))

    @staticmethod
    def _encode_image(container: "ImageContainer") -> str:
        import numpy as np
        from PIL import Image

        pixels = container.pixels
        # Straight bit-depth reduction. Never contrast-stretch: it would show the VLM a
        # normally exposed picture for a dark/bright 16-bit image and hide what needs fixing.
        if pixels.dtype == np.uint16:
            pixels = (pixels >> 8).astype(np.uint8)
        elif pixels.dtype != np.uint8:
            pixels = np.clip(pixels, 0, 255).astype(np.uint8)
        img = Image.fromarray(pixels)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img = Planner._to_srgb(img, container.icc_profile)
        sent = Planner._sent_size(*img.size)
        if sent != img.size:
            img = img.resize(sent, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    @staticmethod
    def _to_srgb(img, icc_profile: bytes | None):
        """Convert from the embedded profile to sRGB so the VLM sees the intended colours."""
        if not isinstance(icc_profile, bytes) or not icc_profile or img.mode != "RGB":
            return img
        try:
            from PIL import ImageCms

            src = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
            if "srgb" in ImageCms.getProfileDescription(src).lower():
                return img
            dst = ImageCms.createProfile("sRGB")
            return ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
        except Exception as exc:  # bad profile must not block planning
            log.debug("icc_to_srgb_failed", error=str(exc))
            return img
