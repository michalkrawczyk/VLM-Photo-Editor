from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject, DetectorModel

from ._common import clamp_bbox, resolve_target_ids, to_rgb_uint8

_INPUT_SIZE = 640
_CONF_THRESHOLD = 0.25
_NMS_THRESHOLD = 0.45
_LAYOUT_HINT = "set model.json 'layout' to yolov8, yolov5 or nms"


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


def _input_size(model: DetectorModel, input_shape: object) -> int:
    """model.json override, else the ONNX input's (square) static size, else 640."""
    if model.input_size:
        return model.input_size
    if isinstance(input_shape, Sequence) and len(input_shape) == 4:
        height, width = input_shape[2], input_shape[3]
        if isinstance(height, int) and height == width and height > 0:
            return height
    return _INPUT_SIZE


def _best_target_scores(
    class_scores: np.ndarray, target_ids: list[int] | None
) -> tuple[np.ndarray, np.ndarray]:
    """Per-row ``(score, class_id)`` restricted to *target_ids* (``None`` = all classes)."""
    if target_ids is None:
        class_ids = np.argmax(class_scores, axis=1)
        return class_scores[np.arange(len(class_ids)), class_ids], class_ids
    ids = np.asarray(target_ids)
    local = np.argmax(class_scores[:, ids], axis=1)
    return class_scores[np.arange(len(local)), ids[local]], ids[local]


def _decode_dense(
    preds: np.ndarray, layout: str, n_labels: int, target_ids: list[int] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """yolov8 ``(N, 4+C)`` / yolov5 ``(N, 5+C)`` -> ``(xywh-topleft, scores, class_ids)``."""
    if preds.shape[0] < preds.shape[1]:
        preds = preds.T  # normalize to (N, attrs)
    extra = 5 if layout == "yolov5" else 4
    num_classes = preds.shape[1] - extra
    if num_classes != n_labels:
        raise ValueError(
            f"yolo_onnx: classes.txt has {n_labels} names but the model emits "
            f"{num_classes} class scores under layout {layout!r} — wrong classes.txt for "
            f"this model, or {_LAYOUT_HINT}."
        )
    scores, class_ids = _best_target_scores(preds[:, extra:], target_ids)
    if layout == "yolov5":
        scores = scores * preds[:, 4]  # objectness x class score
    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, w, h], axis=1)
    return boxes, scores, class_ids


def _decode_nms(
    preds: np.ndarray, n_labels: int, target_ids: list[int] | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """NMS-baked export rows ``x1, y1, x2, y2, score, class_id`` -> same tuple as dense."""
    if preds.ndim != 2 or preds.shape[1] != 6:
        raise ValueError(
            f"yolo_onnx: layout 'nms' expects rows of 6 values (x1,y1,x2,y2,score,class_id) "
            f"but the model output has shape {tuple(preds.shape)}; {_LAYOUT_HINT}."
        )
    class_ids = preds[:, 5].astype(int)
    if class_ids.size and (class_ids.min() < 0 or class_ids.max() >= n_labels):
        raise ValueError(
            f"yolo_onnx: model emitted class id {int(class_ids.max())} but classes.txt has "
            f"only {n_labels} names — wrong classes.txt for this model."
        )
    if target_ids is not None:
        keep = np.isin(class_ids, target_ids)
        preds, class_ids = preds[keep], class_ids[keep]
    boxes = np.stack(
        [preds[:, 0], preds[:, 1], preds[:, 2] - preds[:, 0], preds[:, 3] - preds[:, 1]], axis=1
    )
    return boxes, preds[:, 4], class_ids


def detect(
    container: ImageContainer, model: DetectorModel, target_labels: Sequence[str] | None = None
) -> DetectedSubject | None:
    if not model.path or model.labels is None:
        raise ValueError(f"Detector model {model.id!r} has no model path / classes.txt labels.")
    labels = model.labels
    target_ids = resolve_target_ids(labels, target_labels)
    conf_threshold = model.conf_threshold or _CONF_THRESHOLD

    import cv2
    import onnxruntime as ort

    session = ort.InferenceSession(model.path, providers=["CPUExecutionProvider"])
    model_input = session.get_inputs()[0]
    size = _input_size(model, getattr(model_input, "shape", None))

    rgb = to_rgb_uint8(container.pixels)
    canvas, scale, pad_x, pad_y = _letterbox(rgb, size)
    blob = canvas.astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[None, ...]  # NCHW
    preds = session.run(None, {model_input.name: blob})[0][0]

    if model.layout == "nms":
        boxes, scores, class_ids = _decode_nms(preds, len(labels), target_ids)
    else:
        boxes, scores, class_ids = _decode_dense(preds, model.layout, len(labels), target_ids)

    above = scores >= conf_threshold
    boxes, scores, class_ids = boxes[above], scores[above], class_ids[above]
    if not len(scores):
        return None  # DET-P2: nothing above threshold is a normal result.

    if model.layout == "nms":
        best = int(np.argmax(scores))  # the export already applied NMS
    else:
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), conf_threshold, _NMS_THRESHOLD)
        flat_indices = np.array(indices).flatten()
        if flat_indices.size == 0:
            return None
        best = int(max(flat_indices, key=lambda i: scores[i]))

    x, y, w, h = (float(v) for v in boxes[best])
    # Undo letterbox padding/scale to map back to original-image pixel space.
    orig_x = (x - pad_x) / scale
    orig_y = (y - pad_y) / scale
    orig_w = w / scale
    orig_h = h / scale

    bbox = clamp_bbox(orig_x, orig_y, orig_w, orig_h, container.width, container.height)
    return DetectedSubject(
        bbox=bbox,
        # Class name from the sibling classes.txt (0-based line index == class id).
        label=labels[int(class_ids[best])],
        confidence=float(scores[best]),
        source="yolo_onnx",
    )
