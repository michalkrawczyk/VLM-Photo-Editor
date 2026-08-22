from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from vlm_photo_editor.schema.ops import Backend, OpName, RiskTier


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

    def render_doc(self) -> list[str]:
        return list(self.doc_lines)


# Param-name-keyed bounds, shared across ops (not per-op).
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "ev": (-10.0, 10.0),
    "angle": (-360.0, 360.0),
    "temperature": (1000.0, 20000.0),
    "strength": (0.0, 1.0),
    "inpaint_radius": (1, 100),
    "radius": (0.5, 50.0),
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
        doc_lines=("  rotate: {angle} (float -360 to 360)",),
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
        doc_lines=("  white_balance: {temperature} (float 1000–20000 K)",),
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
        op_name=OpName.DENOISE,
        required_params=(),
        risk_tier=RiskTier.LOW,
        default_backend=Backend.PIL,
        bbox_class=BBoxClass.GENERIC_CONFINABLE,
        ps_expressible=True,
        doc_lines=("  denoise: {}",),
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
            '    op (fill_mask, region_edit with method="blur", exposure, white_balance, or',
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
        requires_bbox=True,
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
    )
)
