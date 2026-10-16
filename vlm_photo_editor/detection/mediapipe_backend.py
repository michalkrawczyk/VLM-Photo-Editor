from __future__ import annotations

from collections.abc import Sequence

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject, DetectorModel

from ._common import clamp_bbox, resolve_target_ids, to_rgb_uint8


def detect(
    container: ImageContainer, model: DetectorModel, target_labels: Sequence[str] | None = None
) -> DetectedSubject | None:
    if not model.path:
        raise ValueError(f"Detector model {model.id!r} has no .tflite model path.")

    # Allowlist uses the model's own category names, so map via its labels (canonical case).
    allowlist: list[str] | None = None
    if model.labels is not None:
        target_ids = resolve_target_ids(model.labels, target_labels)
        if target_ids is not None:
            allowlist = [model.labels[i] for i in target_ids]

    import mediapipe as mp

    # mp.tasks IS mediapipe.tasks.python — there is no further .python attribute on it.
    vision = mp.tasks.vision
    base_options = mp.tasks.BaseOptions(model_asset_path=model.path)
    options = vision.ObjectDetectorOptions(
        base_options=base_options, max_results=1, category_allowlist=allowlist
    )
    detector = vision.ObjectDetector.create_from_options(options)
    rgb = to_rgb_uint8(container.pixels)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_image)
    if not result.detections:
        # DET-P2: a clean run that found nothing is a normal outcome, not a
        # misconfiguration — return None so callers plan without subject context.
        return None

    det = result.detections[0]
    b = det.bounding_box
    bbox = clamp_bbox(b.origin_x, b.origin_y, b.width, b.height, container.width, container.height)
    category = det.categories[0] if det.categories else None
    return DetectedSubject(
        bbox=bbox,
        label=category.category_name if category else "object",
        confidence=float(category.score) if category else 0.0,
        source="mediapipe",
    )
