from __future__ import annotations

from vlm_photo_editor.schema.op_catalog import PARAM_BOUNDS, BBoxClass, get_spec
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName

from .constants import INPAINT_OPS as _INPAINT_OPS


def _as_number(op_name: OpName, key: str, value: object) -> float:
    """Coerce a param to float, raising ValueError (never TypeError) for bad types.

    `bool` is rejected explicitly — it is an `int` subclass and almost always a
    planner mistake for a numeric param.
    """
    if isinstance(value, bool):
        raise ValueError(f"Op {op_name!r} param {key!r} must be a number, got bool {value!r}")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(
            f"Op {op_name!r} param {key!r} must be a number, got {type(value).__name__} {value!r}"
        ) from None


def validate_op(
    op: Op, allowed_ops: set[OpName] | None = None, *, require_bbox: bool = False
) -> None:
    if allowed_ops is not None and op.op_name not in allowed_ops:
        raise ValueError(f"Op {op.op_name!r} not in allowed set")

    if require_bbox and get_spec(op.op_name).requires_bbox and op.bbox is None:
        raise ValueError(f"Op {op.op_name!r} requires a bbox but none was provided")

    required = list(get_spec(op.op_name).required_params)
    if op.op_name in _INPAINT_OPS and op.backend != Backend.GENAI:
        required = [r for r in required if r != "prompt"]
    for key in required:
        if key not in op.params:
            raise ValueError(f"Op {op.op_name!r} missing required param {key!r}")

    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key in op.params:
            val = _as_number(op.op_name, key, op.params[key])
            if not (lo <= val <= hi):
                raise ValueError(f"Param {key!r}={val} out of bounds [{lo}, {hi}]")

    if op.op_name == OpName.CROP:
        left, top, right, bottom = (
            _as_number(op.op_name, k, op.params[k]) for k in ("left", "top", "right", "bottom")
        )
        for k, v in (("left", left), ("top", top), ("right", right), ("bottom", bottom)):
            if v != int(v):
                raise ValueError(f"Crop: {k} ({v}) must be a whole number of pixels")
        if left < 0 or top < 0:
            raise ValueError(f"Crop: coordinates must be non-negative, got left={left} top={top}")
        if left >= right:
            raise ValueError(f"Crop: left ({left}) must be < right ({right})")
        if top >= bottom:
            raise ValueError(f"Crop: top ({top}) must be < bottom ({bottom})")

    if op.bbox is not None and get_spec(op.op_name).bbox_class is BBoxClass.SIZE_CHANGING:
        raise ValueError(f"Op {op.op_name!r} changes image size; bbox not allowed")


def validate_op_graph(
    graph: OpGraph, allowed_ops: set[OpName] | None = None, *, require_bbox: bool = False
) -> None:
    for op in graph.ops:
        validate_op(op, allowed_ops=allowed_ops, require_bbox=require_bbox)


def validate_crop_bounds(op_graph: OpGraph, w: int, h: int) -> None:
    """Raise ValueError if any CROP op exceeds the image dimensions."""
    for op in op_graph.ops:
        if op.op_name != OpName.CROP:
            continue
        p = op.params
        left, top, right, bottom = int(p["left"]), int(p["top"]), int(p["right"]), int(p["bottom"])
        violations = []
        if left < 0:
            violations.append(f"left={left} < 0")
        if top < 0:
            violations.append(f"top={top} < 0")
        if right > w:
            violations.append(f"right={right} > image width {w}")
        if bottom > h:
            violations.append(f"bottom={bottom} > image height {h}")
        if right <= left:
            violations.append(f"right={right} <= left={left}")
        if bottom <= top:
            violations.append(f"bottom={bottom} <= top={top}")
        if violations:
            raise ValueError(
                f"Crop out of bounds for {w}x{h} image "
                f"(left={left} top={top} right={right} bottom={bottom}): "
                + "; ".join(violations)
                + f". Revise crop to fit within [0,{w}] x [0,{h}]."
            )
