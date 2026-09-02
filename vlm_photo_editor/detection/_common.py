from __future__ import annotations

import numpy as np

from vlm_photo_editor.schema.ops import BoundingBox


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
