from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImageStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    NEEDS_REVIEW = "needs_review"
    AUTO_EXECUTED = "auto_executed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class BatchImageRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    image_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str  # original upload name — used for display and save destination
    status: ImageStatus = ImageStatus.PENDING
    container: Any = None  # ImageContainer at runtime; Any avoids circular import
    edited_container: Any = None
    plan: Any = None  # HumanPlan | None
    op_graph: Any = None  # OpGraph | None
    error: str | None = None
    retry_count: int = 0
