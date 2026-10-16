from __future__ import annotations

from vlm_photo_editor.config.policy import EditMode, allowed_ops_for_mode
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.op_catalog import all_specs
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.prefs import Preferences
from vlm_photo_editor.schema.report import ImageReport
from vlm_photo_editor.templates import framing as _framing


def build_system_prompt(
    mode: EditMode | str,
    prefs: Preferences | None,
    framing_intent: FramingIntent | None,
    target_size: tuple[int, int] | None,
    detected_subject: DetectedSubject | None = None,
    genai_available: bool = True,
    image_report: ImageReport | None = None,
) -> str:
    from vlm_photo_editor.config.settings import get_settings

    settings = get_settings()
    no_genai = settings.no_genai
    lines = _base_lines(mode, no_genai, genai_available)
    if settings.ps_mode == "strict":
        lines += _ps_strict_lines()
    lines += _framing_lines(framing_intent, target_size, prefs)
    lines += _subject_detection_lines(detected_subject)
    lines += _measurement_rule_lines(image_report)
    lines += _prefs_lines(prefs, framing_intent)
    return "\n".join(lines)


def revision_rule_lines() -> list[str]:
    """Appended to the system prompt when revising a plan from user feedback."""
    return [
        "",
        "REVISION RULE: you are revising an existing plan. The USER FEEDBACK in the user message "
        "overrides FRAMING INSTRUCTIONS, the target crop size/ratio and subject-detection "
        "anchoring wherever they conflict (e.g. 'crop face only' beats a full-body crop target, and the "
        "detected box is then only a hint to where the face is). Everything else stays binding.",
    ]


def adaptation_rule_lines() -> list[str]:
    """Appended to the system prompt when adapting an approved plan to another image."""
    return [
        "",
        "ADAPTATION RULE: the user approved a REFERENCE PLAN on a different image. Treat it as "
        "the methodology and intent to follow, not as numbers to copy. Re-derive every parameter "
        "(exposure, white balance, crop box, ...) from THIS image's own measurements and geometry; "
        "coordinates are in THIS image's pixel space. Drop, add or reorder steps when this image "
        "needs it (e.g. skip a fix the image does not need). ALLOWED OPS, the active mode and all "
        "other rules above stay binding.",
    ]


def _ps_strict_lines() -> list[str]:
    ps_expressible_ops = [
        spec.op_name.value for spec in all_specs().values() if spec.ps_expressible
    ]
    return [
        "",
        "PS-STRICT MODE: Only propose ops expressible in Photoshop.",
        f"  Allowed PS ops: {ps_expressible_ops}",
        '  Do NOT use backend="genai". Use backend="opencv" for any inpaint op.',
    ]


def _param_constraint_lines() -> list[str]:
    # Unfiltered by allowed_ops_for_mode, matching current behavior — the prose lists
    # all ops regardless of active mode.
    lines: list[str] = []
    for spec in all_specs().values():
        lines.extend(spec.render_doc())
    return lines


def _base_lines(mode: str, no_genai: bool = False, genai_available: bool = True) -> list[str]:
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
        "  diagnosis: 1-2 sentences, photographer vocabulary: what is wrong (or right) with this",
        "    image — exposure, colour, geometry, noise, composition. Write it BEFORE the steps;",
        "    every step must address something named here. If the image needs nothing, say so",
        "    and leave steps empty.",
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
        *_param_constraint_lines(),
        "",
        "INPAINT BACKEND SELECTION (region_edit / background_replace):",
        '  Default is backend="genai": full content synthesis via external API.',
        '  Use backend="opencv" when ALL of the following hold:',
        "    - The object to remove is small (scratch, wire, text, watermark, small spot).",
        "    - No semantic content synthesis is needed (nearby texture can fill the gap).",
        "    - When backend=opencv, omit prompt (it is not used).",
        "",
        'BLUR (region_edit, backend="opencv", method="blur"):',
        "  Use for a deterministic Gaussian blur of a region (e.g. blurred/bokeh background).",
        '  Never use backend="genai" for a plain blur — it is a local, boring, deterministic op.',
        "  Omit prompt. Pair with a preceding mask step to blur everything outside the subject.",
    ]
    if no_genai:
        lines += [
            "",
            'NO-GENAI MODE: Do NOT set backend="genai" for any inpaint op.',
            '  Use backend="opencv" for all region_edit and background_replace ops.',
            "  Omit prompt for these ops.",
        ]
    if not genai_available and not no_genai:
        lines += [
            "",
            "GENAI UNAVAILABLE: No GenAI provider credentials/deps found for the default model.",
            '  Do NOT set backend="genai" for any inpaint op (region_edit, background_replace).',
            '  Use backend="opencv" instead. Omit prompt for these ops.',
        ]
    lines += [
        "",
        "RULES:",
        "  - Only ops from ALLOWED OPS. Never invent op names.",
        "  - op_params[i] matches op_names[i]. Lengths must match.",
        "  - ≤5 steps unless strictly necessary.",
        "  - Never include API keys or secrets.",
        "  - Prefer the smallest edit that achieves the intent. If the image is already fine for",
        "    the intent, return an empty steps list rather than a gratuitous edit.",
        "  - Order steps like a photographer: geometry (crop, rotate, frame) first, then",
        "    white_balance, then exposure, then tone, then saturation, then local edits (mask,",
        "    region_edit, background_replace), then denoise, and sharpen last.",
        "  - Typical magnitudes: exposure ev within -1.5..+1.5 (beyond ±2 is almost always wrong),",
        "    rotate angle within ±5 degrees, tone sliders within ±60, saturation / vibrance within",
        "    ±40, denoise strength 0.2-0.6, sharpen amount 30-100.",
        "  - exposure moves the whole frame; use tone when only the shadows or only the",
        "    highlights need work (e.g. 'Open up shadows' = tone shadows > 0).",
        "",
        "EXAMPLES (shape only — generate fresh UUID step_ids; base numbers on THIS image):",
        *_example_lines(),
    ]
    return lines


# Few-shot plans, kept as data so a test can push every one through the real compiler: if the
# op catalog changes, an example that no longer compiles fails the build instead of teaching
# the model something false.
EXAMPLE_PLANS: tuple[dict, ...] = (
    {
        "situation": "Dark, warm-cast portrait. intent: 'fix the exposure and the orange cast'",
        "diagnosis": "About a stop underexposed with an orange skin cast; highlights are safe.",
        "steps": (
            (
                "Brighten the exposure",
                "Lifts the frame to a natural mid-tone",
                "exposure",
                {"ev": 1.0},
            ),
            (
                "Cool the orange cast",
                "Brings skin back toward neutral",
                "white_balance",
                {"temperature": 5400},
            ),
        ),
    },
    {
        "situation": "Tilted landscape, blown sky. intent: 'straighten and recover the sky'",
        "diagnosis": "Horizon runs about 1.5 degrees off level and the sky is clipping.",
        "steps": (
            (
                "Level the horizon",
                "Removes the slight tilt so the horizon reads straight",
                "rotate",
                {"angle": -1.5, "crop_to_inscribed": True},
            ),
            (
                "Recover the sky",
                "Pulls the clipped sky back into detail",
                "tone",
                {"highlights": -50, "whites": -30},
            ),
        ),
    },
    {
        "situation": "Well-exposed, level, neutral image. intent: 'make it better'",
        "diagnosis": "Exposure, colour and geometry are already sound; nothing needs correcting.",
        "steps": (),
    },
)


def _example_lines() -> list[str]:
    import json

    lines: list[str] = []
    for ex in EXAMPLE_PLANS:
        lines.append(f"  Situation: {ex['situation']}")
        lines.append(f"    diagnosis: {ex['diagnosis']}")
        if not ex["steps"]:
            lines.append("    steps: []")
        for i, (title, why, op, params) in enumerate(ex["steps"], 1):
            lines.append(
                f'    step {i}: title="{title}" why="{why}" op_names=["{op}"] '
                f"op_params=[{json.dumps(params)}]"
            )
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


_RECOMMEND_BEST_EXCLUDED = {FramingMode.CUSTOM, FramingMode.RECOMMEND_BEST}


def _recommend_best_lines(
    framing_intent: FramingIntent,
    prefs: Preferences | None,
) -> list[str]:
    modes = [
        m.value
        for m in FramingMode
        if m not in _RECOMMEND_BEST_EXCLUDED
        and (m is not FramingMode.FACE_ONLY or framing_intent.face_framing_allowed)
    ]
    lines = [
        "",
        "FRAMING — RECOMMEND BEST MODE:",
        "  Examine image composition, subject type, subject placement, and native aspect ratio.",
        f"  Select the single best mode from: {', '.join(modes)}.",
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
    label = detected_subject.label.strip() or "unnamed subject"
    return [
        "",
        "SUBJECT DETECTION:",
        f"  Label: {label}  "
        f"(detector score {detected_subject.confidence:.2f} — not comparable across "
        f"backends; source: {detected_subject.source})",
        f"  Bounding box (px): x={b.x} y={b.y} width={b.width} height={b.height}",
        "  Anchor framing/crop/region-edit reasoning on this box — it is verified, not a guess.",
    ]


def _measurement_rule_lines(image_report: ImageReport | None) -> list[str]:
    """Static rules for using the per-image MEASUREMENTS block; absent when no report is sent."""
    if image_report is None:
        return []
    return [
        "",
        "MEASUREMENT RULES (the user message carries a MEASUREMENTS block for this image):",
        "  - MEASUREMENTS are computed from the pixels. Prefer them to your visual impression",
        "    for exposure, clipping, colour cast and tilt.",
        "  - Do not raise exposure when highlights are clipped above 2 %; recover them with",
        "    tone highlights < 0 (and whites < 0 for blown areas) instead.",
        "  - white_balance: start from the suggested temperature when the cast is not neutral,",
        "    unless the cast is the point of the scene (golden hour, candlelight) or the intent",
        "    asks to keep it. Skip white_balance when the cast is neutral.",
        "  - rotate only when tilt confidence is at least 0.5 and |tilt| is at least 0.5 degrees;",
        "    use angle = -tilt. Otherwise do not rotate.",
        "  - sharpen only when the frame looks soft, and not when noise sigma is above about 3",
        "    (it amplifies grain; denoise first or leave it).",
    ]


def measurement_lines(report: ImageReport) -> list[str]:
    """Render the per-image MEASUREMENTS block (goes in the user message, not the system prompt)."""
    lines = [
        "MEASUREMENTS (computed from the pixels, not estimated):",
        f"  Tone (0=black, 1=white): mean {report.luma_mean:.2f} | P1 {report.luma_p1:.2f} "
        f"P5 {report.luma_p5:.2f} median {report.luma_p50:.2f} "
        f"P95 {report.luma_p95:.2f} P99 {report.luma_p99:.2f}",
        f"  Clipping: shadows {report.clipped_shadow_pct:.1f}% | "
        f"highlights {report.clipped_highlight_pct:.1f}%",
        f"  Colour: cast {report.cast_label} (R/B {report.cast_rb_ratio:.2f}) | suggested "
        f"white_balance temperature {report.suggested_wb_temperature:.0f} "
        f"(higher = warmer) | saturation {report.saturation_mean:.2f}",
        f"  Detail: sharpness {report.sharpness:.0f} | noise sigma {report.noise_sigma:.1f} "
        "(0-255 luma)",
    ]
    if report.tilt_deg is None:
        lines.append("  Geometry: no dominant horizontal/vertical lines found (do not rotate)")
    else:
        lines.append(
            f"  Geometry: tilt {report.tilt_deg:+.1f} deg, confidence "
            f"{report.tilt_confidence or 0.0:.2f} (rotate by {-report.tilt_deg:+.1f} to level)"
        )
    camera = _camera_line(report)
    if camera:
        lines.append(camera)
    return lines


def _camera_line(report: ImageReport) -> str:
    e = report.exif
    parts: list[str] = []
    if e.iso is not None:
        parts.append(f"ISO {e.iso}")
    if e.exposure_time_s:
        t = e.exposure_time_s
        parts.append(f"1/{round(1 / t)} s" if t < 0.5 else f"{t:g} s")
    if e.f_number:
        parts.append(f"f/{e.f_number:g}")
    if e.focal_length_mm:
        parts.append(f"{e.focal_length_mm:g} mm")
    if e.wb_mode:
        parts.append(f"{e.wb_mode} WB")
    if e.exposure_bias_ev is not None:
        parts.append(f"exposure bias {e.exposure_bias_ev:+.1f} EV")
    return f"  Camera: {', '.join(parts)}" if parts else ""


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
