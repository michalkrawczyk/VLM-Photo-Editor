from __future__ import annotations

from enum import Enum

from vlm_photo_editor.schema.ops import OpName


class PolicyMode(str, Enum):
    AUTO = "auto"
    PS_STRICT = "ps_strict"
    NO_PS = "no_ps"


_OP_SETS: dict[str, set[OpName]] = {
    "full": set(OpName),
    "background": {OpName.BACKGROUND_REPLACE, OpName.MASK},
    "frame": {OpName.CROP},
}


def allowed_ops_for_mode(mode: str) -> set[OpName]:
    try:
        return _OP_SETS[mode]
    except KeyError:
        raise KeyError(f"Unknown edit mode: {mode!r}. Valid: {sorted(_OP_SETS)}")
