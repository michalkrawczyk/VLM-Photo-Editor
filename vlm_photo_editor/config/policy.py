from __future__ import annotations

from enum import Enum

from vlm_photo_editor.schema.ops import OpName


class PolicyMode(str, Enum):
    AUTO = "auto"
    PS_STRICT = "ps_strict"
    NO_PS = "no_ps"


class EditMode(str, Enum):
    FULL = "full"
    BACKGROUND = "background"
    FRAME = "frame"


_OP_SETS: dict[str, set[OpName]] = {
    "full": set(OpName),
    "background": {OpName.BACKGROUND_REPLACE, OpName.MASK},
    "frame": {OpName.CROP},
    # Policy modes: all ops reachable; backend enforcement is in the compiler
    "auto": set(OpName),
    "ps_strict": set(OpName),
    "no_ps": set(OpName),
}


def allowed_ops_for_mode(mode: EditMode | str) -> set[OpName]:
    try:
        return _OP_SETS[mode]
    except KeyError:
        raise KeyError(f"Unknown edit mode: {mode!r}. Valid: {sorted(_OP_SETS)}")
