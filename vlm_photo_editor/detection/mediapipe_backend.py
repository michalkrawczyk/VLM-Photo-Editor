from __future__ import annotations

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject

from ._common import clamp_bbox, to_rgb_uint8


def detect(container: ImageContainer) -> DetectedSubject:
    from vlm_photo_editor.config.settings import get_settings

    model_path = get_settings().mediapipe_model_path
    if not model_path:
        raise ValueError(
            "Character Focus backend 'mediapipe' requires AppSettings.mediapipe_model_path "
            "to be set to a downloaded .tflite object-detector model file."
        )

    import mediapipe as mp

    vision = mp.tasks.python.vision
    base_options = mp.tasks.python.core.base_options.BaseOptions(model_asset_path=model_path)
    options = vision.ObjectDetectorOptions(base_options=base_options, max_results=1)
    detector = vision.ObjectDetector.create_from_options(options)
    rgb = to_rgb_uint8(container.pixels)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = detector.detect(mp_image)
    if not result.detections:
        raise ValueError("mediapipe: no subject detected in image")

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
