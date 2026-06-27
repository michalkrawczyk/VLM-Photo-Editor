from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .ops import OpGraph


class GenAIOp(BaseModel):
    step_id: str
    model: str
    prompt: str
    seed: int


class Recipe(BaseModel):
    recipe_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_path: str
    op_graph: OpGraph
    genai_ops: list[GenAIOp] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    branch: str = "main"
