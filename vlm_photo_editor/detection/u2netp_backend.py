from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject

from ._common import clamp_bbox, to_rgb_uint8

_INPUT_SIZE = 320


def detect(container: ImageContainer) -> DetectedSubject | None:
    from vlm_photo_editor.config.settings import get_settings

    model_path = get_settings().u2netp_model_path
    if not model_path:
        raise ValueError(
            "Character Focus backend 'u2netp' requires AppSettings.u2netp_model_path "
            "to be set to a u2netp .onnx model file."
        )

    import cv2
    import onnxruntime as ort

    rgb = to_rgb_uint8(container.pixels)
    h, w = rgb.shape[:2]
    resized = cv2.resize(rgb, (_INPUT_SIZE, _INPUT_SIZE)).astype(np.float32) / 255.0
    blob = resized.transpose(2, 0, 1)[None, ...]  # NCHW

    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: blob})[0]  # (1, 1, H, W) saliency mask

    mask = cv2.resize(output[0, 0], (w, h))
    mask_u8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
    _, binary = cv2.threshold(mask_u8, 127, 255, cv2.THRESH_BINARY)

    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    if num_labels <= 1:
        # DET-P2: no salient region is a normal result, not a misconfiguration.
        return None

    # Label 0 is background; pick the largest non-background component by area.
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, cw, ch, _area = stats[largest]
    confidence = float(mask[y : y + ch, x : x + cw].mean())

    bbox = clamp_bbox(x, y, cw, ch, w, h)
    return DetectedSubject(
        bbox=bbox, label="salient_object", confidence=confidence, source="u2netp"
    )
