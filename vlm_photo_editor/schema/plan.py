from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .ops import FramingMode, OpGraph, OpName

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class HumanStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("step_id", mode="before")
    @classmethod
    def _require_uuid_format(cls, v: object) -> str:
        s = str(v)
        if not _UUID_RE.match(s):
            raise ValueError(f"step_id {s!r} is not a valid UUID")
        return s

    index: int = Field(ge=0)
    title: str
    why: str
    op_names: list[OpName] = Field(default_factory=list)
    op_params: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_parity(self) -> "HumanStep":
        if len(self.op_names) != len(self.op_params):
            raise ValueError(
                f"op_names ({len(self.op_names)}) and op_params ({len(self.op_params)}) "
                "must have equal length"
            )
        return self


class HumanPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    steps: list[HumanStep] = Field(default_factory=list)
    mode: str = "full"
    chosen_framing_mode: FramingMode | None = None
    chosen_framing_why: str | None = None
    outpaint_needed: bool = False


class CompilerResult(BaseModel):
    plan: HumanPlan
    op_graph: OpGraph
