from __future__ import annotations

from pydantic import BaseModel, Field

from .ops import BoundingBox


class DetectedSubject(BaseModel):
    """One backend's best guess at the primary subject's location.

    DET-P3: ``label`` and ``confidence`` are NOT comparable across backends —
    each detector fills them with whatever it has:

    | source     | ``label``              | ``confidence``                |
    |------------|------------------------|-------------------------------|
    | mediapipe  | COCO category name      | classifier softmax score      |
    | yolo_onnx  | ``""`` (no name map)    | class score                   |
    | u2netp     | ``"salient_object"``    | mean saliency over the bbox   |

    Treat ``confidence`` as a rough per-detector score in 0-1, never as a
    cross-source probability; ``label`` may be empty when the backend cannot name
    what it found.
    """

    bbox: BoundingBox
    label: str = Field(
        description="Human-readable class name, or '' when the backend cannot name the subject."
    )
    confidence: float = Field(
        description="Detector-reported score, 0-1. Not comparable across sources (see class doc)."
    )
    source: str
