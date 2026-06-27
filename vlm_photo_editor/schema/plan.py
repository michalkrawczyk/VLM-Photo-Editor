from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from .ops import FramingMode, OpGraph, OpName


class HumanStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int = Field(ge=0)
    title: str
    why: str
    op_names: list[OpName] = Field(default_factory=list)
    op_params: list[dict[str, Any]] = Field(default_factory=list)


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
