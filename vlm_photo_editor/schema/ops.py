from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OpName(str, Enum):
    CROP = "crop"
    ROTATE = "rotate"
    WHITE_BALANCE = "white_balance"
    EXPOSURE = "exposure"
    DENOISE = "denoise"
    MASK = "mask"
    FILL_MASK = "fill_mask"
    REGION_EDIT = "region_edit"
    BACKGROUND_REPLACE = "background_replace"
    FRAME = "frame"


class Backend(str, Enum):
    PIL = "pil"
    OPENCV = "opencv"
    GENAI = "genai"
    PHOTOSHOP = "photoshop"


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


class FramingMode(str, Enum):
    RULE_OF_THIRDS = "rule_of_thirds"
    GOLDEN_RATIO = "golden_ratio"
    GOLDEN_SPIRAL = "golden_spiral"
    CENTER_SYMMETRY = "center_symmetry"
    PORTRAIT_HEADROOM = "portrait_headroom"
    FACE_ONLY = "face_only"
    NEGATIVE_SPACE = "negative_space"
    FILL_FRAME = "fill_frame"
    LEAD_ROOM = "lead_room"
    HORIZON_THIRD = "horizon_third"
    CUSTOM = "custom"
    RECOMMEND_BEST = "recommend_best"


class AcceptMode(str, Enum):
    MANUAL = "manual"
    AUTO_LOW = "auto_low"  # auto-approve if all ops are LOW risk
    AUTO_MEDIUM = "auto_medium"  # auto-approve if all ops are LOW or MEDIUM risk
    FULL_AUTO = "full_auto"  # always auto-approve


class CharacterFocusBackend(str, Enum):
    OFF = "off"
    MEDIAPIPE = "mediapipe"
    YOLO_ONNX = "yolo_onnx"
    U2NETP = "u2netp"


class BoundingBox(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Op(BaseModel):
    op_name: OpName
    backend: Backend = Backend.PIL
    params: dict[str, Any] = Field(default_factory=dict)
    bbox: BoundingBox | None = None
    risk_tier: RiskTier = RiskTier.LOW
    step_id: str


class OpGraph(BaseModel):
    ops: list[Op] = Field(default_factory=list)


class FramingIntent(BaseModel):
    mode: FramingMode
    focus_instruction: str = ""
    frame_ratio: str | None = None
    user_instruction: str | None = None
