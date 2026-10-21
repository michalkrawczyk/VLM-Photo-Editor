from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from .ops import OpGraph

# v1 (no field on disk): white_balance used "higher K = cooler", gamma-space exposure/WB.
# v2: Lightroom WB direction (higher K = warmer), linear-light exposure/WB.
# RecipeStore.load migrates v1 sidecars; bump this when op semantics change again.
RECIPE_SCHEMA_VERSION = 2


class GenAIOp(BaseModel):
    step_id: str
    model: str
    prompt: str
    # BG-P2: None when the provider's API accepts no seed (OpenAI images.edit, Google
    # Imagen edit). A fabricated seed reproduces nothing — such a step is regenerated
    # fresh on replay rather than pretending to be deterministic.
    seed: int | None = None


class Recipe(BaseModel):
    schema_version: int = RECIPE_SCHEMA_VERSION
    recipe_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_path: str
    op_graph: OpGraph
    genai_ops: list[GenAIOp] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    branch: str = "main"

    @field_validator("source_path")
    @classmethod
    def _source_path_is_plain(cls, v: str) -> str:
        # S-D3: sidecars are loaded from disk, so source_path is untrusted input that
        # replay later opens. Reject the shapes that escape the folder it names; the
        # schema layer cannot know an allowed root, so this is hardening, not containment.
        if not v.strip():
            raise ValueError("source_path must not be empty")
        if "\x00" in v:
            raise ValueError("source_path must not contain NUL bytes")
        if ".." in re.split(r"[\\/]", v):
            raise ValueError("source_path must not contain '..' segments")
        return v
