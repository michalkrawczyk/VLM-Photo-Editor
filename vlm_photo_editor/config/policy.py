from __future__ import annotations

from enum import Enum

from vlm_photo_editor.schema.ops import OpName, RiskTier


class PolicyMode(str, Enum):
    AUTO = "auto"
    PS_STRICT = "ps_strict"
    NO_PS = "no_ps"


_RISK_ORDER = [RiskTier.LOW, RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.DESTRUCTIVE]
_AUTO_MANUAL_THRESHOLD = RiskTier.HIGH


def requires_manual_approval(tier: RiskTier, mode: PolicyMode) -> bool:
    if mode == PolicyMode.AUTO:
        return _RISK_ORDER.index(tier) >= _RISK_ORDER.index(_AUTO_MANUAL_THRESHOLD)
    return True


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
