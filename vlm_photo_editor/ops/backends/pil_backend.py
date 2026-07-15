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
        OpName.FRAME: _frame,
        OpName.MASK: _mask,
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
    h, w = container.pixels.shape[:2]
    if left < 0 or top < 0 or right > w or bottom > h or right <= left or bottom <= top:
        raise ValueError(
            f"crop params out of bounds: left={left} top={top} right={right} bottom={bottom}"
            f" image={w}x{h}"
        )
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
    factor = 2.0**ev
    max_val = 65535.0 if container.bit_depth == 16 else 255.0
    pixels = np.clip(container.pixels.astype(np.float64) * factor, 0, max_val)
    result = container.copy()
    result.pixels = pixels.astype(container.pixels.dtype)
    return result


def _denoise(container: ImageContainer, params: dict) -> ImageContainer:
    img = _to_pil_8bit(container)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return _from_pil(img, container)


def _mask(container: ImageContainer, params: dict) -> ImageContainer:
    fill = int(params.get("fill", 0))
    max_val = 65535 if container.bit_depth == 16 else 255
    fill = max(0, min(fill, max_val))
    result = container.copy()
    result.pixels = np.full_like(container.pixels, fill)
    return result


_FRAME_ASPECT: dict[str, tuple[int, int]] = {
    "rule_of_thirds": (4, 3),
    "golden_ratio": (1618, 1000),
    "golden_spiral": (1618, 1000),
    "center_symmetry": (1, 1),
    "portrait_headroom": (3, 4),
    "face_only": (3, 4),
    "negative_space": (16, 9),
    "fill_frame": (0, 0),  # sentinel: no-op
    "lead_room": (16, 9),
    "horizon_third": (16, 9),
}


def frame_target_size(w: int, h: int, composition: str) -> tuple[int, int] | None:
    """Return (target_w, target_h) for a composition crop, or None for fill_frame."""
    aspect = _FRAME_ASPECT.get(composition, (4, 3))
    if aspect == (0, 0):
        return None
    tw, th = aspect
    if w / h > tw / th:
        return int(h * tw / th), h
    return w, int(w * th / tw)


def frame_crop_box(w: int, h: int, mode: str, params: dict) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) for a FRAME composition crop, or None for fill_frame."""
    target = frame_target_size(w, h, mode)
    if target is None:
        return None
    target_w, target_h = target

    focus_keys = ("focus_x", "focus_y", "focus_w", "focus_h")
    if all(k in params for k in focus_keys):
        cx = float(params["focus_x"]) + float(params["focus_w"]) / 2
        cy = float(params["focus_y"]) + float(params["focus_h"]) / 2
        left = int(round(cx - target_w / 2))
        top = int(round(cy - target_h / 2))
    else:
        left = (w - target_w) // 2
        top = (h - target_h) // 2

    left = max(0, min(left, w - target_w))
    top = max(0, min(top, h - target_h))
    return left, top, left + target_w, top + target_h


def _frame(container: ImageContainer, params: dict) -> ImageContainer:
    mode = str(params.get("mode", "rule_of_thirds"))
    h, w = container.pixels.shape[:2]
    box = frame_crop_box(w, h, mode, params)
    if box is None:
        return container.copy()
    left, top, right, bottom = box
    result = container.copy()
    result.pixels = container.pixels[top:bottom, left:right]
    return result
