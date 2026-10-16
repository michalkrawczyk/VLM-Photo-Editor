from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from vlm_photo_editor.schema.ops import Backend, FramingMode, OpName, RiskTier


class BBoxClass(str, Enum):
    SIZE_CHANGING = "size_changing"
    SELF_MANAGED_INPAINT = "self_managed_inpaint"
    GENERIC_CONFINABLE = "generic_confinable"


@dataclass(frozen=True)
class OpSpec:
    op_name: OpName
    required_params: tuple[str, ...]
    risk_tier: RiskTier
    default_backend: Backend
    bbox_class: BBoxClass
    ps_expressible: bool
    doc_lines: tuple[str, ...]
    requires_bbox: bool = False
    # SC-B1: allowed values for string params (name -> choices). Numeric ranges live
    # in PARAM_BOUNDS; this closes the gap for enum-like params such as `frame.mode`
    # and `region_edit.method`, where a bogus value otherwise validates and no-ops.
    enum_params: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # S-C1 / SC-S1: keys a backend legitimately reads beyond `required_params`.
    # `validate_op` rejects any param key outside required ∪ optional ∪ the
    # compiler-injected set (`invert`, `focus_*`) — closing the open `params` dict so
    # a typo'd key ("angl") fails at plan time, not at backend dispatch.
    optional_params: tuple[str, ...] = ()

    def render_doc(self) -> list[str]:
        return list(self.doc_lines)


# Param-name-keyed bounds, shared across ops (not per-op).
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "ev": (-10.0, 10.0),
    "angle": (-360.0, 360.0),
    "temperature": (1000.0, 20000.0),
    "strength": (0.0, 1.0),
    # tone sliders, Lightroom-style -100..100
    "shadows": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "whites": (-100.0, 100.0),
    "blacks": (-100.0, 100.0),
    "contrast": (-100.0, 100.0),
    # colour-intensity sliders, Lightroom-style -100..100
    "saturation": (-100.0, 100.0),
    "vibrance": (-100.0, 100.0),
    "inpaint_radius": (1, 100),
    "radius": (0.5, 50.0),
    "amount": (0.0, 300.0),  # sharpen strength, percent
    "threshold": (0.0, 255.0),  # sharpen: min local contrast, 8-bit luma levels
    "n": (1, 8),  # genAI candidate count — caps planner/recipe-controlled paid calls (OE-S1)
}

_CATALOG: dict[OpName, OpSpec] = {}


def register_op(spec: OpSpec, *, replace: bool = False) -> None:
    if not replace and spec.op_name in _CATALOG:
        raise ValueError(f"OpName {spec.op_name!r} already registered")
    _CATALOG[spec.op_name] = spec


def get_spec(op_name: OpName) -> OpSpec:
    return _CATALOG[op_name]  # KeyError if missing — fail loud, not silent default


def all_specs() -> Mapping[OpName, OpSpec]:
    return MappingProxyType(_CATALOG)


register_op(
    OpSpec(
        op_name=OpName.CROP,
        required_params=("left", "top", "right", "bottom"),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.SIZE_CHANGING,
        ps_expressible=True,
        doc_lines=(
            "  crop: {left, top, right, bottom} (pixel ints; 0 ≤ left < right ≤ image_width, 0 ≤ top < bottom ≤ image_height)",
        ),
    )
)

register_op(
    OpSpec(
        op_name=OpName.ROTATE,
        required_params=("angle",),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.SIZE_CHANGING,
        ps_expressible=True,
        doc_lines=(
            "  rotate: {angle, crop_to_inscribed} (angle: float -360 to 360, counter-clockwise;",
            "    crop_to_inscribed: bool, optional, default false — true trims the empty corners",
            "    so a small straighten leaves no black wedges)",
        ),
        optional_params=("crop_to_inscribed",),  # pil_backend._rotate
    )
)

register_op(
    OpSpec(
        op_name=OpName.WHITE_BALANCE,
        required_params=("temperature",),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  white_balance: {temperature} (float 1000–20000 K, Lightroom convention: 6500 is",
            "    neutral; HIGHER = WARMER / more orange, LOWER = COOLER / more blue;",
            "    typical 3500–9000)",
        ),
    )
)

register_op(
    OpSpec(
        op_name=OpName.EXPOSURE,
        required_params=("ev",),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=("  exposure: {ev} (float -10 to 10)",),
    )
)

register_op(
    OpSpec(
        op_name=OpName.TONE,
        required_params=(),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  tone: {shadows, highlights, whites, blacks, contrast} (each optional, float",
            "    -100 to 100, 0 = unchanged; typical ±20-60). A tone curve: shadows lifts (+) or",
            "    deepens (-) the dark tones, highlights brightens (+) or recovers (-) the bright",
            "    tones, both leaving pure black and pure white in place; blacks / whites move the",
            "    black and white points (whites < 0 greys out blown white, blacks < 0 crushes",
            "    shadows); contrast > 0 steepens the midtones. Use it instead of exposure when",
            "    only one end of the range needs work",
        ),
        optional_params=("shadows", "highlights", "whites", "blacks", "contrast"),
    )
)

register_op(
    OpSpec(
        op_name=OpName.SATURATION,
        required_params=(),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  saturation: {saturation, vibrance} (each optional, float -100 to 100, 0 =",
            "    unchanged; typical ±10-40). saturation scales every colour's intensity equally",
            "    (-100 = greyscale); vibrance moves muted colours more than already-vivid ones,",
            "    so it avoids over-saturating. Prefer vibrance for a gentle lift",
        ),
        optional_params=("saturation", "vibrance"),
    )
)

register_op(
    OpSpec(
        op_name=OpName.DENOISE,
        required_params=(),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=("  denoise: {}",),
        optional_params=("strength",),  # cv_backend._denoise
    )
)

register_op(
    OpSpec(
        op_name=OpName.SHARPEN,
        required_params=(),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  sharpen: {amount, radius, threshold} (all optional; amount float 0-300 %, default",
            "    50, typical 30-100; radius float 0.5-50 px, default 1.0, typical 0.6-1.5;",
            "    threshold float 0-255, default 0 — local contrast below it is left alone, raise",
            "    it to keep skin and sky smooth). Unsharp mask on luminance only, so no colour",
            "    fringes. Put it after denoise and do not use it on a noisy image",
        ),
        optional_params=("amount", "radius", "threshold"),
    )
)

register_op(
    OpSpec(
        op_name=OpName.MASK,
        required_params=(),
        risk_tier=RiskTier.MEDIUM,
        # Never actually consulted: MASK is folded away by _collapse_mask_ops before
        # reaching a real Op. Placeholder values, harmless — flagged so this isn't
        # mistaken for a behavior change later.
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  mask: {} — protects the subject. Must be immediately followed by exactly one other",
            '    op (fill_mask, region_edit with method="blur", exposure, tone, white_balance, or',
            "    denoise), which then applies ONLY OUTSIDE the subject. Uses the Character Focus",
            "    detected subject if active; otherwise the user is prompted to draw a Region",
            "    Selection at execute time. Cannot precede crop, rotate, frame, background_replace,",
            '    or region_edit without method="blur".',
        ),
    )
)

register_op(
    OpSpec(
        op_name=OpName.FILL_MASK,
        required_params=(),
        risk_tier=RiskTier.MEDIUM,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=(
            "  fill_mask: {fill} (int, optional, default 0) — paints the selected region a flat",
            "    color. Standalone op; needs its own region (drawn manually, or inherited by",
            "    immediately following a mask step).",
        ),
        requires_bbox=True,
        optional_params=("fill",),  # pil_backend._fill_mask
    )
)

register_op(
    OpSpec(
        op_name=OpName.REGION_EDIT,
        required_params=("prompt",),
        risk_tier=RiskTier.HIGH,
        default_backend=Backend.GENAI,
        bbox_class=BBoxClass.SELF_MANAGED_INPAINT,
        ps_expressible=True,
        doc_lines=(
            '  region_edit: {prompt: str (required for genai), backend: "genai"|"opencv" (optional),',
            '    method: "telea"|"ns"|"blur" (opencv only, default "telea"),',
            '    radius: float 0.5-50 (opencv method="blur" only, default 15, Gaussian blur strength)}',
        ),
        enum_params=(("method", ("telea", "ns", "blur")),),
        requires_bbox=True,
        # genai: model/n/seed; opencv method="blur": method/radius
        optional_params=("method", "radius", "model", "n", "seed"),
    )
)

register_op(
    OpSpec(
        op_name=OpName.BACKGROUND_REPLACE,
        required_params=("prompt",),
        risk_tier=RiskTier.HIGH,
        default_backend=Backend.GENAI,
        bbox_class=BBoxClass.SELF_MANAGED_INPAINT,
        ps_expressible=False,
        doc_lines=(
            '  background_replace: {prompt: str (required for genai), backend: "genai"|"opencv" (optional)}',
        ),
        requires_bbox=True,
        # genai: model/n/seed; opencv (apply_inpaint): inpaint_radius/method
        optional_params=("model", "n", "seed", "inpaint_radius", "method"),
    )
)

register_op(
    OpSpec(
        op_name=OpName.FRAME,
        required_params=("mode",),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.SIZE_CHANGING,
        ps_expressible=False,
        doc_lines=(
            "  frame: {mode: str} — one of: rule_of_thirds, golden_ratio, golden_spiral,",
            "    center_symmetry, portrait_headroom, face_only, negative_space,",
            "    fill_frame, lead_room, horizon_third",
        ),
        enum_params=(("mode", tuple(m.value for m in FramingMode)),),
    )
)
