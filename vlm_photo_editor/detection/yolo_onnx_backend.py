from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject

from ._common import clamp_bbox, has_human_label, load_class_labels, to_rgb_uint8

_INPUT_SIZE = 640
_CONF_THRESHOLD = 0.25
_NMS_THRESHOLD = 0.45


def _letterbox(rgb: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    import cv2

    h, w = rgb.shape[:2]
    scale = min(size / w, size / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(rgb, (new_w, new_h))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
    return canvas, scale, pad_x, pad_y


def detect(container: ImageContainer) -> DetectedSubject | None:
    from vlm_photo_editor.config.settings import get_settings

    model_path = get_settings().yolo_onnx_model_path
    if not model_path:
        raise ValueError(
            "Character Focus backend 'yolo_onnx' requires AppSettings.yolo_onnx_model_path "
            "to be set to an exported YOLO .onnx model file."
        )

    labels = load_class_labels(model_path)  # raises a clear ValueError if absent/empty
    if not has_human_label(labels):
        raise ValueError(
            f"Character Focus backend 'yolo_onnx': classes.txt next to {model_path} "
            "must contain a 'human' or 'person' class."
        )

    import cv2
    import onnxruntime as ort

    rgb = to_rgb_uint8(container.pixels)
    canvas, scale, pad_x, pad_y = _letterbox(rgb, _INPUT_SIZE)
    blob = canvas.astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[None, ...]  # NCHW

    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: blob})[0]

    preds = outputs[0]
    if preds.shape[0] < preds.shape[1]:
        preds = preds.T  # normalize to (N, 4 + num_classes[+obj])

    num_classes = preds.shape[1] - 4
    if num_classes != len(labels):
        raise ValueError(
            f"yolo_onnx: classes.txt has {len(labels)} names but the model emits "
            f"{num_classes} class scores — wrong classes.txt for this model."
        )

    boxes: list[list[float]] = []
    scores: list[float] = []
    class_ids: list[int] = []
    for row in preds:
        cx, cy, w, h = row[:4]
        class_scores = row[4:]
        class_id = int(np.argmax(class_scores))
        score = float(class_scores[class_id])
        if score < _CONF_THRESHOLD:
            continue
        boxes.append([float(cx - w / 2), float(cy - h / 2), float(w), float(h)])
        scores.append(score)
        class_ids.append(class_id)

    if not boxes:
        return None  # DET-P2: nothing above threshold is a normal result.

    indices = cv2.dnn.NMSBoxes(boxes, scores, _CONF_THRESHOLD, _NMS_THRESHOLD)
    flat_indices = np.array(indices).flatten()
    if flat_indices.size == 0:
        return None
    best = int(max(flat_indices, key=lambda i: scores[i]))

    x, y, w, h = boxes[best]
    # Undo letterbox padding/scale to map back to original-image pixel space.
    orig_x = (x - pad_x) / scale
    orig_y = (y - pad_y) / scale
    orig_w = w / scale
    orig_h = h / scale

    bbox = clamp_bbox(orig_x, orig_y, orig_w, orig_h, container.width, container.height)
    return DetectedSubject(
        bbox=bbox,
        # Class name from the sibling classes.txt (0-based line index == class id).
        label=labels[class_ids[best]],
        confidence=scores[best],
        source="yolo_onnx",
    )
