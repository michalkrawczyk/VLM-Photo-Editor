from __future__ import annotations

import numpy as np

from vlm_photo_editor.schema.ops import BoundingBox


def clamp_bbox(x: float, y: float, w: float, h: float, img_w: int, img_h: int) -> BoundingBox:
    """Clamp a (possibly out-of-bounds) detector box into [0, img_w) x [0, img_h)."""
    x0 = max(0, min(int(x), img_w - 1))
    y0 = max(0, min(int(y), img_h - 1))
    x1 = max(x0 + 1, min(int(round(x + w)), img_w))
    y1 = max(y0 + 1, min(int(round(y + h)), img_h))
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
