from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import BoundingBox


def bbox_to_mask(container: ImageContainer, bbox: BoundingBox) -> np.ndarray:
    """Return bool mask (H, W), True inside the bbox."""
    if bbox.x < 0 or bbox.y < 0:
        raise ValueError(f"BoundingBox origin ({bbox.x}, {bbox.y}) must be non-negative")
    if bbox.x >= container.width or bbox.y >= container.height:
        raise ValueError(
            f"BoundingBox origin ({bbox.x}, {bbox.y}) is outside the "
            f"{container.width}x{container.height} image; the region edit would be a no-op"
        )
    mask = np.zeros((container.height, container.width), dtype=bool)
    x2 = min(bbox.x + bbox.width, container.width)
    y2 = min(bbox.y + bbox.height, container.height)
    mask[bbox.y : y2, bbox.x : x2] = True
    return mask
