from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ExplicitRule(BaseModel):
    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    active: bool = True


class LearnedRule(BaseModel):
    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    active: bool = False
    approved: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Preferences(BaseModel):
    version: str = Field(default_factory=lambda: str(uuid.uuid4()))
    explicit: list[ExplicitRule] = Field(default_factory=list)
    learned: list[LearnedRule] = Field(default_factory=list)
    # Normalized descriptions of dismissed learned rules; the aggregator must not resurrect them.
    dismissed: list[str] = Field(default_factory=list)


class EditDelta(BaseModel):
    delta_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    intent: str
    mode: str
    change_requests: list[str] = Field(default_factory=list)
    accepted_ops: list[str] = Field(default_factory=list)
