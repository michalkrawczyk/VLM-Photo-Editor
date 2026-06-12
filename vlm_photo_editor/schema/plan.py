from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from .ops import OpGraph


class HumanStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    index: int
    title: str
    why: str
    op_names: list[str] = Field(default_factory=list)


class HumanPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    steps: list[HumanStep] = Field(default_factory=list)
    mode: str = "full"


class CompilerResult(BaseModel):
    plan: HumanPlan
    op_graph: OpGraph
