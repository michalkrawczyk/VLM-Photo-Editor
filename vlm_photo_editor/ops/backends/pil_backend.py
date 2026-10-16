from __future__ import annotations

import math

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op, OpName


def apply(container: ImageContainer, op: Op) -> ImageContainer:
    dispatch = {
        OpName.CROP: _crop,
        OpName.ROTATE: _rotate,
        OpName.WHITE_BALANCE: _white_balance,
        OpName.EXPOSURE: _exposure,
        OpName.TONE: _tone,
        OpName.SATURATION: _saturation,
        OpName.DENOISE: _denoise,
        OpName.SHARPEN: _sharpen,
        OpName.FRAME: _frame,
        OpName.FILL_MASK: _fill_mask,
    }
    fn = dispatch.get(op.op_name)
    if fn is None:
        raise ValueError(f"PIL backend does not support op {op.op_name!r}")
    return fn(container, op.params)


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


def _inscribed_size(w: int, h: int, angle_deg: float) -> tuple[float, float]:
    """Width/height of the largest axis-aligned rect inside a w x h rect rotated by angle."""
    a = math.radians(angle_deg)
    sin_a, cos_a = abs(math.sin(a)), abs(math.cos(a))
    width_is_longer = w >= h
    side_long, side_short = (w, h) if width_is_longer else (h, w)
    if side_short <= 2.0 * sin_a * cos_a * side_long or abs(sin_a - cos_a) < 1e-10:
        # Two crop corners touch the longer side: half-constrained case.
        x = 0.5 * side_short
        return (x / sin_a, x / cos_a) if width_is_longer else (x / cos_a, x / sin_a)
    cos_2a = cos_a * cos_a - sin_a * sin_a
    return (w * cos_a - h * sin_a) / cos_2a, (h * cos_a - w * sin_a) / cos_2a


def _rotate(container: ImageContainer, params: dict) -> ImageContainer:
    import cv2

    angle = float(params["angle"])
    pixels = container.pixels
    h, w = pixels.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)  # counter-clockwise, like PIL
    cos_a, sin_a = abs(m[0, 0]), abs(m[0, 1])
    # round() first: cos(90deg) is ~6e-17, which would otherwise ceil to one extra pixel.
    new_w = int(math.ceil(round(h * sin_a + w * cos_a, 6)))
    new_h = int(math.ceil(round(h * cos_a + w * sin_a, 6)))
    m[0, 2] += new_w / 2.0 - w / 2.0
    m[1, 2] += new_h / 2.0 - h / 2.0
    # Native dtype in/out: uint16 stays uint16, alpha is rotated with the colour channels.
    rotated = cv2.warpAffine(
        np.ascontiguousarray(pixels),
        m,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    if params.get("crop_to_inscribed", False) is True:
        wr, hr = _inscribed_size(w, h, angle)
        # -2 px: the exact inscribed edge is a half-blended interpolation row/column.
        cw = max(1, min(new_w, int(math.floor(wr)) - 2))
        ch = max(1, min(new_h, int(math.floor(hr)) - 2))
        left, top = (new_w - cw) // 2, (new_h - ch) // 2
        rotated = rotated[top : top + ch, left : left + cw]
    result = container.copy()
    result.pixels = rotated
    return result


# Highlight shoulder starts here (linear light); below it exposure is a pure multiply.
_SHOULDER_KNEE = 0.8


def _srgb_to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055)


def _linear_lut(dtype: np.dtype, fn) -> np.ndarray:
    """Per-code-value table for a linear-light function: decode sRGB, `fn`, re-encode, round."""
    max_val = int(np.iinfo(dtype).max)
    linear = _srgb_to_linear(np.arange(max_val + 1, dtype=np.float64) / max_val)
    return np.rint(_linear_to_srgb(fn(linear)) * max_val).astype(dtype)


def _map_channels(container: ImageContainer, luts: dict[int, np.ndarray]) -> ImageContainer:
    result = container.copy()
    if result.pixels.ndim == 2:
        result.pixels = luts[0][result.pixels]
        return result
    for channel, lut in luts.items():
        result.pixels[..., channel] = lut[result.pixels[..., channel]]
    return result


def _white_balance(container: ImageContainer, params: dict) -> ImageContainer:
    # Lightroom convention: temperature is the light the scene is declared to have, so a
    # higher value warms the image (red up, blue down) and a lower one cools it.
    temp = float(params["temperature"])
    deviation = (temp - 6500.0) / 6500.0
    r_mult = max(0.1, 1.0 + 0.5 * deviation)
    b_mult = max(0.1, 1.0 - 0.5 * deviation)

    pixels = container.pixels
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        return container.copy()
    dtype = pixels.dtype
    return _map_channels(
        container,
        {
            0: _linear_lut(dtype, lambda lin: lin * r_mult),
            2: _linear_lut(dtype, lambda lin: lin * b_mult),
        },
    )


def _exposure(container: ImageContainer, params: dict) -> ImageContainer:
    factor = 2.0 ** float(params["ev"])
    knee = _SHOULDER_KNEE

    def expose(lin: np.ndarray) -> np.ndarray:
        scaled = lin * factor
        if factor <= 1.0:
            return scaled
        # Extended-Reinhard shoulder above the knee, white point = the brightest value this
        # ev can produce: identity as ev -> 0, white stays white, no hard clip, C1 at the knee.
        x = np.maximum(scaled - knee, 0.0) / (1.0 - knee)
        w = (factor - knee) / (1.0 - knee)
        shoulder = knee + (1.0 - knee) * (x + x * x / (w * w)) / (1.0 + x)
        return np.where(scaled > knee, shoulder, scaled)

    pixels = container.pixels
    lut = _linear_lut(pixels.dtype, expose)
    colour_channels = 1 if pixels.ndim == 2 else min(3, pixels.shape[2])  # alpha untouched
    return _map_channels(container, {c: lut for c in range(colour_channels)})


_TONE_KEYS = ("shadows", "highlights", "whites", "blacks", "contrast")


def _tone_curve(x: np.ndarray, params: dict) -> np.ndarray:
    """Tone curve on display-referred 0-1 values; every slider at 0 is the identity.

    shadows/highlights are bumps that vanish at 0 and 1, so pure black and pure white stay
    put; blacks/whites are steep end-weighted terms that move the black and white points;
    contrast is an S-curve pivoting at 0.5. Each term alone stays monotonic for |slider|
    <= 100; the running maximum keeps the sum monotonic too.
    """
    s = {k: float(params.get(k, 0.0)) / 100.0 for k in _TONE_KEYS}
    y = (
        x
        + s["shadows"] * x * (1.0 - x) ** 4
        + s["highlights"] * x**4 * (1.0 - x)
        + 0.1 * s["blacks"] * (1.0 - x) ** 8
        + 0.1 * s["whites"] * x**8
        + 0.9 * s["contrast"] * x * (1.0 - x) * (2.0 * x - 1.0)
    )
    return np.maximum.accumulate(np.clip(y, 0.0, 1.0))


def _tone(container: ImageContainer, params: dict) -> ImageContainer:
    pixels = container.pixels
    max_val = int(np.iinfo(pixels.dtype).max)
    codes = np.arange(max_val + 1, dtype=np.float64) / max_val
    lut = np.rint(_tone_curve(codes, params) * max_val).astype(pixels.dtype)
    colour_channels = 1 if pixels.ndim == 2 else min(3, pixels.shape[2])  # alpha untouched
    return _map_channels(container, {c: lut for c in range(colour_channels)})


def _saturation(container: ImageContainer, params: dict) -> ImageContainer:
    """Scale chroma about each pixel's luma; both sliders at 0 is the identity.

    Display-referred like ``tone`` (slider convention). ``saturation`` scales every pixel by
    ``1 + s``; ``vibrance`` scales by ``1 + v * (1 - chroma)`` so already-vivid pixels move less.
    """
    pixels = container.pixels
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        return container.copy()
    sat = float(params.get("saturation", 0.0)) / 100.0
    vib = float(params.get("vibrance", 0.0)) / 100.0
    if sat == 0.0 and vib == 0.0:
        return container.copy()
    max_val = float(np.iinfo(pixels.dtype).max)
    rgb = pixels[..., :3].astype(np.float32) / max_val
    luma = (rgb * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(axis=-1, keepdims=True)
    peak = rgb.max(axis=-1, keepdims=True)
    chroma = (peak - rgb.min(axis=-1, keepdims=True)) / np.maximum(peak, 1e-6)
    gain = np.maximum(1.0 + sat + vib * (1.0 - chroma), 0.0)
    out = np.clip(luma + (rgb - luma) * gain, 0.0, 1.0)
    result = container.copy()
    result.pixels[..., :3] = np.rint(out * max_val).astype(pixels.dtype)
    return result


def _denoise(container: ImageContainer, params: dict) -> ImageContainer:
    import cv2

    # strength absent => 1.0 (full 3x3 median), the pre-strength behaviour saved recipes rely on.
    strength = float(params.get("strength", 1.0))
    pixels = container.pixels
    has_alpha = pixels.ndim == 3 and pixels.shape[2] == 4
    color = pixels[..., :3] if has_alpha else pixels
    # medianBlur ksize 3 runs natively on uint8 and uint16 — no 8-bit round trip.
    median = cv2.medianBlur(np.ascontiguousarray(color), 3)
    if strength < 1.0:
        blended = color.astype(np.float32) + strength * (median.astype(np.float32) - color)
        median = np.rint(blended).astype(pixels.dtype)
    denoised = np.concatenate([median, pixels[..., 3:]], axis=2) if has_alpha else median
    result = container.copy()
    result.pixels = denoised
    return result


def _sharpen(container: ImageContainer, params: dict) -> ImageContainer:
    """Unsharp mask on luma only: the detail (luma - blurred luma) is added to all channels.

    ``threshold`` is in 8-bit luma levels (scaled for 16-bit); detail below it is dropped.
    amount 0 is the identity.
    """
    import cv2

    pixels = container.pixels
    amount = float(params.get("amount", 50.0)) / 100.0
    if amount == 0.0 or pixels.ndim != 3 or pixels.shape[2] < 3:
        return container.copy()
    radius = float(params.get("radius", 1.0))
    threshold = float(params.get("threshold", 0.0)) / 255.0
    max_val = float(np.iinfo(pixels.dtype).max)
    rgb = pixels[..., :3].astype(np.float32) / max_val
    luma = (rgb * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(axis=-1)
    detail = luma - cv2.GaussianBlur(luma, (0, 0), radius)
    detail = np.where(np.abs(detail) > threshold, detail, 0.0)
    out = np.clip(rgb + (amount * detail)[..., None], 0.0, 1.0)
    result = container.copy()
    result.pixels[..., :3] = np.rint(out * max_val).astype(pixels.dtype)
    return result


def _fill_mask(container: ImageContainer, params: dict) -> ImageContainer:
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
