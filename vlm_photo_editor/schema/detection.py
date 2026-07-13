from __future__ import annotations

from pydantic import BaseModel

from .ops import BoundingBox


class DetectedSubject(BaseModel):
    bbox: BoundingBox
    label: str
    confidence: float
    source: str
