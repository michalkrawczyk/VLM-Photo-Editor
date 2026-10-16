from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .ops import BoundingBox, CharacterFocusBackend

DetectorLayout = Literal["yolov8", "yolov5", "nms"]
DetectorOrigin = Literal["legacy", "discovered", "user"]


class DetectedSubject(BaseModel):
    """One backend's best guess at the primary subject's location.

    DET-P3: ``label`` and ``confidence`` are NOT comparable across backends —
    each detector fills them with whatever it has:

    | source     | ``label``               | ``confidence``                |
    |------------|-------------------------|-------------------------------|
    | mediapipe  | COCO category name       | classifier softmax score      |
    | yolo_onnx  | class name from classes.txt | class score                |
    | u2netp     | ``"salient_object"``     | mean saliency over the bbox   |

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


class DetectorModel(BaseModel):
    """One selectable Character Focus detector model (bundled, dropped-in, or user-added).

    ``backend`` is the runtime family that executes it; several models can share one
    backend. ``labels`` is the class vocabulary (0-based index == class id) or ``None``
    for class-agnostic detectors. A model that cannot run carries ``invalid_reason``
    instead of being dropped, so the UI can say why.
    """

    id: str
    display_name: str
    backend: CharacterFocusBackend
    path: str | None = None
    labels: list[str] | None = None
    origin: DetectorOrigin
    layout: DetectorLayout = "yolov8"
    input_size: int | None = Field(default=None, gt=0)
    conf_threshold: float | None = Field(default=None, gt=0, le=1)
    invalid_reason: str | None = None
