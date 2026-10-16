from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .ops import FramingMode, OpGraph, OpName


class HumanStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("step_id", mode="before")
    @classmethod
    def _require_uuid_format(cls, v: object) -> str:
        # Accept any RFC-4122 spelling (dashed, bare 32-hex, urn:, braces — VLMs vary);
        # store the canonical dashed form so step-ID linkage stays byte-comparable.
        try:
            return str(uuid.UUID(str(v)))
        except ValueError:
            raise ValueError(f"step_id {v!r} is not a valid UUID") from None

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
    # What is right/wrong with the image, in photographer terms. Written before the steps so
    # the model commits to a read of the picture first; shown to the user, never executed.
    diagnosis: str = ""
    steps: list[HumanStep] = Field(default_factory=list)
    mode: str = "full"
    chosen_framing_mode: FramingMode | None = None
    chosen_framing_why: str | None = None
    outpaint_needed: bool = False


class CompilerResult(BaseModel):
    plan: HumanPlan
    op_graph: OpGraph
