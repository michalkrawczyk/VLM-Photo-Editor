from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np

from vlm_photo_editor.schema.ops import BoundingBox

# Class names that satisfy the "must be able to detect people" requirement for an
# ONNX detection model's sibling classes.txt. COCO ships "person", not "human".
_HUMAN_ALIASES = frozenset({"human", "person"})


def load_class_labels(model_path: str | Path) -> list[str]:
    """Read the ``classes.txt`` sitting next to an ONNX detection model.

    One class name per line; line index is the class id (0-based). Interior blank
    lines are kept so the index stays aligned to the model's class scores; only
    trailing blanks are dropped. Raises ``ValueError`` (naming the expected path)
    when the file is absent, unreadable, or holds no class names — callers treat
    that as "backend not ready", never as a silent fallback.
    """
    labels_file = Path(model_path).with_name("classes.txt")
    if not labels_file.is_file():
        raise ValueError(
            f"ONNX detection model {model_path} requires a sibling classes.txt "
            f"(one class name per line, 0-based); none found at {labels_file}."
        )
    try:
        text = labels_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"classes.txt at {labels_file} is unreadable: {exc}") from exc
    labels = [line.strip() for line in text.splitlines()]
    while labels and not labels[-1]:
        labels.pop()
    if not any(labels):
        raise ValueError(f"classes.txt at {labels_file} has no class names")
    return labels


def has_human_label(labels: Iterable[str]) -> bool:
    """True when ``labels`` contains a human/person class (case-insensitive)."""
    return any(name.strip().casefold() in _HUMAN_ALIASES for name in labels)


def clamp_bbox(x: float, y: float, w: float, h: float, img_w: int, img_h: int) -> BoundingBox:
    """Clamp a detector box to the image; raise if it does not overlap the image.

    DET-P1: a box that falls entirely off the image used to be forced to a 1x1 px
    box, which then became the subject-freeze region and let genAI regenerate the
    whole frame. A non-overlapping box is a detector/coordinate-mapping failure, not
    a valid subject — fail loudly instead.
    """
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(int(round(x + w)), img_w)
    y1 = min(int(round(y + h)), img_h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            f"detection box (x={x}, y={y}, w={w}, h={h}) has no overlap with "
            f"{img_w}x{img_h} image"
        )
    return BoundingBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def to_rgb_uint8(pixels: np.ndarray) -> np.ndarray:
    """Downconvert to 8-bit and normalize to a contiguous HxWx3 RGB array."""
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    if pixels.ndim == 2:
        pixels = np.stack([pixels] * 3, axis=-1)
    elif pixels.shape[2] == 4:
        pixels = pixels[..., :3]
    return np.ascontiguousarray(pixels)
