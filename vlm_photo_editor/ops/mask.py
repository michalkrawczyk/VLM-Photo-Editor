from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import BoundingBox


def bbox_to_mask(container: ImageContainer, bbox: BoundingBox) -> np.ndarray:
    """Return bool mask (H, W), True inside the bbox."""
    mask = np.zeros((container.height, container.width), dtype=bool)
    x2 = min(bbox.x + bbox.width, container.width)
    y2 = min(bbox.y + bbox.height, container.height)
    mask[bbox.y : y2, bbox.x : x2] = True
    return mask
