from __future__ import annotations

from vlm_photo_editor.config.policy import EditMode, allowed_ops_for_mode
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.prefs import Preferences
from vlm_photo_editor.templates import framing as _framing


def build_system_prompt(
    mode: EditMode | str,
    prefs: Preferences | None,
    framing_intent: FramingIntent | None,
    target_size: tuple[int, int] | None,
    detected_subject: DetectedSubject | None = None,
) -> str:
    from vlm_photo_editor.config.settings import get_settings

    settings = get_settings()
    no_genai = settings.no_genai
    lines = _base_lines(mode, no_genai)
    if settings.ps_mode == "strict":
        lines += _ps_strict_lines()
    lines += _framing_lines(framing_intent, target_size, prefs)
    lines += _subject_detection_lines(detected_subject)
    lines += _prefs_lines(prefs, framing_intent)
    return "\n".join(lines)


_PS_EXPRESSIBLE_OPS = [
    "crop",
    "rotate",
    "white_balance",
    "exposure",
    "denoise",
    "mask",
    "region_edit",
]


def _ps_strict_lines() -> list[str]:
    return [
        "",
        "PS-STRICT MODE: Only propose ops expressible in Photoshop.",
        f"  Allowed PS ops: {_PS_EXPRESSIBLE_OPS}",
        '  Do NOT use backend="genai". Use backend="opencv" for any inpaint op.',
    ]


def _base_lines(mode: str, no_genai: bool = False) -> list[str]:
    try:
        allowed = sorted(op.value for op in allowed_ops_for_mode(mode))
    except KeyError as exc:
        raise ValueError(f"Unknown edit mode for prompt builder: {mode!r}") from exc
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
        "    step_id: UUID v4 string — hex digits 0-9 and a-f ONLY, no g-z (stable)",
        "    index: 1-based int",
        "    title: ≤8 words, photographer vocabulary (e.g. 'Open up shadows', 'Recover highlights', 'Warm the midtones')",
        "    why: one sentence in photographer language — describe the visual/tonal outcome, not the technical op (e.g. 'Opens up underexposed shadow detail to reveal texture', 'Cools the midtones to match the overcast light', 'Tightens the frame to place the subject on the thirds')",
        "    op_names: list[str] from ALLOWED OPS only",
        "    op_params: list[dict] — one dict per op_name (same order)",
        "  chosen_framing_mode: null or string (fill only in RECOMMEND_BEST mode)",
        "  chosen_framing_why: null or string (fill only in RECOMMEND_BEST mode)",
        "  outpaint_needed: bool (default false; set true when crop would clip the primary subject)",
        "",
        "PARAM CONSTRAINTS:",
        "  crop: {left, top, right, bottom} (pixel ints; 0 ≤ left < right ≤ image_width, 0 ≤ top < bottom ≤ image_height)",
        "  rotate: {angle} (float -360 to 360)",
        "  white_balance: {temperature} (float 1000–20000 K)",
        "  exposure: {ev} (float -10 to 10)",
        "  denoise: {}",
        "  mask: {}",
        '  region_edit: {prompt: str (required for genai), backend: "genai"|"opencv" (optional)}',
        '  background_replace: {prompt: str (required for genai), backend: "genai"|"opencv" (optional)}',
        "  frame: {mode: str} — one of: rule_of_thirds, golden_ratio, golden_spiral,",
        "    center_symmetry, portrait_headroom, face_only, negative_space,",
        "    fill_frame, lead_room, horizon_third",
        "",
        "INPAINT BACKEND SELECTION (region_edit / background_replace):",
        '  Default is backend="genai": full content synthesis via external API.',
        '  Use backend="opencv" when ALL of the following hold:',
        "    - The object to remove is small (scratch, wire, text, watermark, small spot).",
        "    - No semantic content synthesis is needed (nearby texture can fill the gap).",
        "    - When backend=opencv, omit prompt (it is not used).",
    ]
    if no_genai:
        lines += [
            "",
            'NO-GENAI MODE: Do NOT set backend="genai" for any inpaint op.',
            '  Use backend="opencv" for all region_edit and background_replace ops.',
            "  Omit prompt for these ops.",
        ]
    lines += [
        "",
        "RULES:",
        "  - Only ops from ALLOWED OPS. Never invent op names.",
        "  - op_params[i] matches op_names[i]. Lengths must match.",
        "  - ≤5 steps unless strictly necessary.",
        "  - Never include API keys or secrets.",
    ]
    return lines


def _framing_lines(
    framing_intent: FramingIntent | None,
    target_size: tuple[int, int] | None,
    prefs: Preferences | None,
) -> list[str]:
    if framing_intent is None:
        return []
    if framing_intent.mode is FramingMode.RECOMMEND_BEST:
        return _recommend_best_lines(framing_intent, prefs)
    return _specific_framing_lines(framing_intent, target_size)


def _specific_framing_lines(
    framing_intent: FramingIntent,
    target_size: tuple[int, int] | None,
) -> list[str]:
    mode_val = framing_intent.mode.value
    ratio = framing_intent.frame_ratio or _framing.frame_ratio_str(framing_intent.mode) or ""
    focus = framing_intent.focus_instruction or _framing.focus_instruction(framing_intent.mode)

    lines = ["", "FRAMING INSTRUCTIONS:"]
    if ratio:
        lines.append(f"  Composition: {mode_val}  →  Frame ratio: {ratio}")
    else:
        lines.append(f"  Composition: {mode_val}")
    if target_size:
        tw, th = target_size
        lines.append(f"  Target crop: {tw}×{th} px")
    if focus:
        lines.append(f"  Focus: {focus}")
    lines.append("  - Output exactly one 'crop' step.")
    if target_size:
        tw, th = target_size
        lines.append(f"  - right - left == {tw}, bottom - top == {th}.")
    lines += [
        "  - If satisfying this framing without clipping the primary subject is impossible,",
        "    set outpaint_needed=true and omit the crop step.",
    ]
    return lines


def _recommend_best_lines(
    framing_intent: FramingIntent,
    prefs: Preferences | None,
) -> list[str]:
    lines = [
        "",
        "FRAMING — RECOMMEND BEST MODE:",
        "  Examine image composition, subject type, subject placement, and native aspect ratio.",
        "  Select the single best mode from: rule_of_thirds, golden_ratio, golden_spiral,",
        "    center_symmetry, portrait_headroom, face_only, negative_space, fill_frame, lead_room, horizon_third.",
        "  Set chosen_framing_mode to the chosen mode value (exact string).",
        "  Set chosen_framing_why to a one-sentence compositional reason in photographer terms (e.g. 'Subject falls in dead centre — thirds crop adds visual tension').",
        "  Output one 'crop' step using crop coordinates for the chosen mode and ratio.",
        "  If no crop can preserve the primary subject, set outpaint_needed=true and omit crop step.",
    ]
    if framing_intent.user_instruction:
        lines.append(f'  USER INSTRUCTION (highest priority): "{framing_intent.user_instruction}"')
    if prefs:
        active_explicit = [r.description for r in prefs.explicit if r.active]
        active_learned = [r.description for r in prefs.learned if r.active and r.approved]
        all_prefs = active_explicit + active_learned
        if all_prefs:
            lines.append("  FRAMING PREFERENCES (soft constraints):")
            lines += [f"    - {d}" for d in all_prefs]
    return lines


def _subject_detection_lines(detected_subject: DetectedSubject | None) -> list[str]:
    if detected_subject is None:
        return []
    b = detected_subject.bbox
    return [
        "",
        "SUBJECT DETECTION:",
        f"  Label: {detected_subject.label}  "
        f"(confidence {detected_subject.confidence:.2f}, source: {detected_subject.source})",
        f"  Bounding box (px): x={b.x} y={b.y} width={b.width} height={b.height}",
        "  Anchor framing/crop/region-edit reasoning on this box — it is verified, not a guess.",
    ]


def _prefs_lines(prefs: Preferences | None, framing_intent: FramingIntent | None) -> list[str]:
    # Preferences for RECOMMEND_BEST are already embedded in _recommend_best_lines
    if framing_intent and framing_intent.mode is FramingMode.RECOMMEND_BEST:
        return []
    if not prefs:
        return []
    active_explicit = [r.description for r in prefs.explicit if r.active]
    active_learned = [r.description for r in prefs.learned if r.active and r.approved]
    lines: list[str] = []
    if active_explicit:
        lines += ["", "USER PREFERENCES (highest priority):"]
        lines += [f"  - {d}" for d in active_explicit]
    if active_learned:
        lines += ["", "LEARNED PREFERENCES:"]
        lines += [f"  - {d}" for d in active_learned]
    return lines
