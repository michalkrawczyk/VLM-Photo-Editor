from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op, OpName


def apply(container: ImageContainer, op: Op) -> ImageContainer:
    if op.op_name == OpName.DENOISE:
        return _denoise(container, op.params)
    raise ValueError(f"OpenCV backend does not support op {op.op_name!r}")


def apply_inpaint(container: ImageContainer, op: Op) -> ImageContainer:
    """Inpaint the region defined by op.bbox using cv2.inpaint (no API call required).

    Supports BACKGROUND_REPLACE and REGION_EDIT. Requires op.bbox; raises if absent.
    Params: inpaint_radius (int, default 5), method ("telea"|"ns", default "telea").
    """
    import cv2

    from vlm_photo_editor.ops.mask import bbox_to_mask

    if op.bbox is None:
        raise ValueError(f"Op {op.op_name!r} with opencv backend requires a bbox")

    pixels = container.pixels
    is_16bit = container.bit_depth == 16
    pixels_8 = (pixels >> 8).astype(np.uint8) if is_16bit else pixels.astype(np.uint8)

    mask_bool = bbox_to_mask(container, op.bbox)
    mask_uint8 = mask_bool.astype(np.uint8) * 255

    radius = int(op.params.get("inpaint_radius", 5))
    method_name = op.params.get("method", "telea")
    if method_name not in {"telea", "ns"}:
        raise ValueError(f"inpaint method {method_name!r} must be 'telea' or 'ns'")
    flags = cv2.INPAINT_NS if method_name == "ns" else cv2.INPAINT_TELEA

    has_alpha = pixels_8.ndim == 3 and pixels_8.shape[2] == 4
    inpaint_input = pixels_8[..., :3] if has_alpha else pixels_8

    inpainted_rgb = cv2.inpaint(inpaint_input, mask_uint8, radius, flags)
    inpainted_8 = np.dstack([inpainted_rgb, pixels_8[..., 3]]) if has_alpha else inpainted_rgb

    result = container.copy()
    if is_16bit:
        combined = pixels.copy()
        combined[mask_bool] = (inpainted_8[mask_bool].astype(np.uint16)) << 8
        result.pixels = combined
    else:
        combined = pixels.copy()
        combined[mask_bool] = inpainted_8[mask_bool]
        result.pixels = combined

    outside = ~mask_bool
    if not np.all(result.pixels[outside] == container.pixels[outside]):
        raise RuntimeError("CV inpaint: pixels outside bbox were modified — invariant violated")

    return result


def _denoise(container: ImageContainer, params: dict) -> ImageContainer:
    import cv2

    pixels = container.pixels
    if pixels.dtype == np.uint16:
        pixels_8 = (pixels >> 8).astype(np.uint8)
    else:
        pixels_8 = pixels.astype(np.uint8)

    strength = float(params.get("strength", 0.5))
    h = int(strength * 20) + 1  # maps [0,1] → [1,21]

    has_alpha = pixels_8.ndim == 3 and pixels_8.shape[2] == 4
    denoise_input = pixels_8[..., :3] if has_alpha else pixels_8

    if denoise_input.ndim == 3 and denoise_input.shape[2] == 3:
        denoised_rgb = cv2.fastNlMeansDenoisingColored(denoise_input, None, h, h, 7, 21)
    else:
        denoised_rgb = cv2.fastNlMeansDenoising(denoise_input, None, h, 7, 21)

    denoised = np.dstack([denoised_rgb, pixels_8[..., 3]]) if has_alpha else denoised_rgb

    result = container.copy()
    if container.bit_depth == 16:
        result.pixels = denoised.astype(np.uint16) << 8
    else:
        result.pixels = denoised
    return result
