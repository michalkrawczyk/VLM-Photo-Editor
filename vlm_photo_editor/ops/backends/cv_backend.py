from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op, OpName


def apply(container: ImageContainer, op: Op) -> ImageContainer:
    if op.op_name == OpName.DENOISE:
        return _denoise(container, op.params)
    raise ValueError(f"OpenCV backend does not support op {op.op_name!r}")


def _denoise(container: ImageContainer, params: dict) -> ImageContainer:
    import cv2

    pixels = container.pixels
    if pixels.dtype == np.uint16:
        pixels_8 = (pixels >> 8).astype(np.uint8)
    else:
        pixels_8 = pixels.astype(np.uint8)

    strength = float(params.get("strength", 0.5))
    h = int(strength * 20) + 1  # maps [0,1] → [1,21]

    if pixels_8.ndim == 3 and pixels_8.shape[2] == 3:
        denoised = cv2.fastNlMeansDenoisingColored(pixels_8, None, h, h, 7, 21)
    else:
        denoised = cv2.fastNlMeansDenoising(pixels_8, None, h, 7, 21)

    result = container.copy()
    if container.bit_depth == 16:
        result.pixels = denoised.astype(np.uint16) << 8
    else:
        result.pixels = denoised
    return result
