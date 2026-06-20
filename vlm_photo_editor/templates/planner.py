from __future__ import annotations

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.prefs import Preferences


def build_system_prompt(
    mode: str,
    prefs: Preferences | None,
    framing_intent: FramingIntent | None,
    target_size: tuple[int, int] | None,
) -> str:
    lines = _base_lines(mode)
    lines += _framing_lines(framing_intent, target_size, prefs)
    lines += _prefs_lines(prefs, framing_intent)
    return "\n".join(lines)


def _base_lines(mode: str) -> list[str]:
    allowed = sorted(op.value for op in allowed_ops_for_mode(mode))
    return [
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
    ratio = framing_intent.frame_ratio or ""
    lines = ["", "FRAMING INSTRUCTIONS:"]
    if ratio:
        lines.append(f"  Composition: {mode_val}  →  Frame ratio: {ratio}")
    else:
        lines.append(f"  Composition: {mode_val}")
    if target_size:
        tw, th = target_size
        lines.append(f"  Target crop: {tw}×{th} px")
    if framing_intent.focus_instruction:
        lines.append(f"  Focus: {framing_intent.focus_instruction}")
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
        "  Set chosen_framing_why to a one-sentence justification.",
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
