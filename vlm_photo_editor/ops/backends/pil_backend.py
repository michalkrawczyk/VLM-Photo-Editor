from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op, OpName


def apply(container: ImageContainer, op: Op) -> ImageContainer:
    dispatch = {
        OpName.CROP: _crop,
        OpName.ROTATE: _rotate,
        OpName.WHITE_BALANCE: _white_balance,
        OpName.EXPOSURE: _exposure,
        OpName.DENOISE: _denoise,
    }
    fn = dispatch.get(op.op_name)
    if fn is None:
        raise ValueError(f"PIL backend does not support op {op.op_name!r}")
    return fn(container, op.params)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_pil_8bit(container: ImageContainer) -> Image.Image:
    pixels = container.pixels
    if pixels.dtype == np.uint16:
        pixels = (pixels >> 8).astype(np.uint8)
    if pixels.ndim == 2:
        return Image.fromarray(pixels, "L")
    if pixels.shape[2] == 4:
        return Image.fromarray(pixels, "RGBA")
    return Image.fromarray(pixels, "RGB")


def _from_pil(img: Image.Image, source: ImageContainer) -> ImageContainer:
    pixels = np.array(img)
    return ImageContainer(
        pixels=pixels,
        bit_depth=8,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=source.metadata,
    )


# ---------------------------------------------------------------------------
# Op implementations
# ---------------------------------------------------------------------------

def _crop(container: ImageContainer, params: dict) -> ImageContainer:
    left = int(params["left"])
    top = int(params["top"])
    right = int(params["right"])
    bottom = int(params["bottom"])
    result = container.copy()
    result.pixels = container.pixels[top:bottom, left:right]
    return result


def _rotate(container: ImageContainer, params: dict) -> ImageContainer:
    img = _to_pil_8bit(container)
    rotated = img.rotate(float(params["angle"]), expand=True)
    return _from_pil(rotated, container)


def _white_balance(container: ImageContainer, params: dict) -> ImageContainer:
    temp = float(params["temperature"])
    deviation = (temp - 6500.0) / 6500.0
    r_mult = max(0.1, 1.0 - 0.5 * deviation)
    b_mult = max(0.1, 1.0 + 0.5 * deviation)

    max_val = 65535.0 if container.bit_depth == 16 else 255.0
    pixels = container.pixels.astype(np.float64)
    if pixels.ndim == 3 and pixels.shape[2] >= 3:
        pixels[..., 0] = np.clip(pixels[..., 0] * r_mult, 0, max_val)
        pixels[..., 2] = np.clip(pixels[..., 2] * b_mult, 0, max_val)
    result = container.copy()
    result.pixels = pixels.astype(container.pixels.dtype)
    return result


def _exposure(container: ImageContainer, params: dict) -> ImageContainer:
    ev = float(params["ev"])
    factor = 2.0 ** ev
    max_val = 65535.0 if container.bit_depth == 16 else 255.0
    pixels = np.clip(container.pixels.astype(np.float64) * factor, 0, max_val)
    result = container.copy()
    result.pixels = pixels.astype(container.pixels.dtype)
    return result


def _denoise(container: ImageContainer, params: dict) -> ImageContainer:
    img = _to_pil_8bit(container)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return _from_pil(img, container)
