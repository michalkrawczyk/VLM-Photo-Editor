from __future__ import annotations

from vlm_photo_editor.schema.ops import Op, OpGraph, OpName

_REQUIRED_PARAMS: dict[OpName, list[str]] = {
    OpName.CROP: ["left", "top", "right", "bottom"],
    OpName.ROTATE: ["angle"],
    OpName.WHITE_BALANCE: ["temperature"],
    OpName.EXPOSURE: ["ev"],
    OpName.DENOISE: [],
    OpName.MASK: [],
    OpName.REGION_EDIT: ["prompt"],
    OpName.BACKGROUND_REPLACE: ["prompt"],
    OpName.FRAME: ["mode"],
}

_PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "ev": (-10.0, 10.0),
    "angle": (-360.0, 360.0),
    "temperature": (1000.0, 20000.0),
    "strength": (0.0, 1.0),
}

# Ops that change image dimensions cannot be confined to a bbox.
_SIZE_CHANGING_OPS = {OpName.CROP, OpName.ROTATE, OpName.FRAME}


def validate_op(op: Op, allowed_ops: set[OpName] | None = None) -> None:
    if allowed_ops is not None and op.op_name not in allowed_ops:
        raise ValueError(f"Op {op.op_name!r} not in allowed set")

    required = _REQUIRED_PARAMS.get(op.op_name, [])
    for key in required:
        if key not in op.params:
            raise ValueError(f"Op {op.op_name!r} missing required param {key!r}")

    for key, (lo, hi) in _PARAM_BOUNDS.items():
        if key in op.params:
            val = float(op.params[key])
            if not (lo <= val <= hi):
                raise ValueError(f"Param {key!r}={val} out of bounds [{lo}, {hi}]")

    if op.bbox is not None and op.op_name in _SIZE_CHANGING_OPS:
        raise ValueError(f"Op {op.op_name!r} changes image size; bbox not allowed")


def validate_op_graph(graph: OpGraph, allowed_ops: set[OpName] | None = None) -> None:
    for op in graph.ops:
        validate_op(op, allowed_ops=allowed_ops)
