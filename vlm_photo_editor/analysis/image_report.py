from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from vlm_photo_editor.analysis.exif import parse_exif
from vlm_photo_editor.schema.report import ImageReport

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer

_ANALYSIS_LONG_EDGE = 1024
_NOISE_CROP = 1024
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)  # Rec.709
_SHADOW_MAX = 2 / 255
_HIGHLIGHT_MIN = 253 / 255
_CAST_THRESHOLD = 0.08  # |R/B - 1| beyond this is called warm/cool
_NEUTRAL_K = 6500.0  # must match pil_backend._white_balance
_TEMPERATURE_BOUNDS = (1000.0, 20000.0)  # must match PARAM_BOUNDS["temperature"]
_TILT_MAX_DEG = 15.0  # steeper "lines" are diagonals, not a horizon/vertical
_TILT_AGREE_DEG = 1.0


def _to_rgb01(pixels: np.ndarray) -> np.ndarray:
    """HxWx3 float32 in 0-1 (gamma-encoded), alpha dropped, gray promoted."""
    scale = 65535.0 if pixels.dtype == np.uint16 else 255.0
    arr = pixels.astype(np.float32) / scale
    if arr.ndim == 2:
        arr = arr[..., None]
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    return np.ascontiguousarray(arr[..., :3])


def _downscale(rgb: np.ndarray) -> np.ndarray:
    import cv2

    h, w = rgb.shape[:2]
    long_edge = max(h, w)
    if long_edge <= _ANALYSIS_LONG_EDGE:
        return rgb
    factor = _ANALYSIS_LONG_EDGE / long_edge
    size = (max(1, round(w * factor)), max(1, round(h * factor)))
    return cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)


def _srgb_to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _noise_sigma(rgb_full: np.ndarray) -> float:
    """Immerkaer fast noise estimate on a native-resolution centre crop (0-255 luma)."""
    import cv2

    h, w = rgb_full.shape[:2]
    top, left = max(0, (h - _NOISE_CROP) // 2), max(0, (w - _NOISE_CROP) // 2)
    crop = rgb_full[top : top + _NOISE_CROP, left : left + _NOISE_CROP]
    ch, cw = crop.shape[:2]
    if ch < 3 or cw < 3:
        return 0.0
    luma = (crop @ _LUMA) * 255.0
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    response = cv2.filter2D(luma.astype(np.float32), cv2.CV_32F, kernel)[1:-1, 1:-1]
    return float(math.sqrt(math.pi / 2) / 6.0 * np.abs(response).mean())


def _tilt(luma01: np.ndarray) -> tuple[float | None, float | None]:
    """Length-weighted median angle of near-horizontal/vertical Hough segments."""
    import cv2

    gray = np.rint(luma01 * 255.0).astype(np.uint8)
    h, w = gray.shape
    long_edge = max(h, w)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 720,
        threshold=max(30, long_edge // 12),
        minLineLength=long_edge * 0.2,
        maxLineGap=long_edge * 0.02,
    )
    if lines is None:
        return None, None
    seg = lines.reshape(-1, 4).astype(np.float64)  # (N,1,4) on cv2 4.x, (N,4) on 5.x
    dx, dy = seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]
    length = np.hypot(dx, dy)
    # Visual counter-clockwise angle (image y points down), folded to [-45, 45) so a
    # near-vertical edge reports its lean from vertical.
    angle = -np.degrees(np.arctan2(dy, dx))
    angle = angle - 90.0 * np.round(angle / 90.0)
    keep = np.abs(angle) <= _TILT_MAX_DEG
    if not keep.any():
        return None, None
    angle, length = angle[keep], length[keep]
    order = np.argsort(angle)
    cum = np.cumsum(length[order])
    median = float(angle[order][np.searchsorted(cum, cum[-1] / 2.0)])
    inlier = length[np.abs(angle - median) <= _TILT_AGREE_DEG].sum()
    agreement = inlier / length.sum()
    coverage = min(1.0, inlier / long_edge)
    return median, float(agreement * coverage)


def compute_report(container: "ImageContainer") -> ImageReport:
    """Measure ``container`` deterministically (no RNG, no network, no VLM)."""
    rgb_full = _to_rgb01(container.pixels)
    rgb = _downscale(rgb_full)
    luma = rgb @ _LUMA

    p1, p5, p50, p95, p99 = (float(v) for v in np.percentile(luma, [1, 5, 50, 95, 99]))
    peak = rgb.max(axis=2)
    shadow_pct = float((peak <= _SHADOW_MAX).mean() * 100.0)
    highlight_pct = float((peak >= _HIGHLIGHT_MIN).mean() * 100.0)

    means = rgb.reshape(-1, 3).mean(axis=0)
    lin = _srgb_to_linear(rgb).reshape(-1, 3).mean(axis=0)
    eps = 1e-6
    rb_ratio = float(lin[0] / max(lin[2], eps))
    # Gray-world: pick d so (1 + d/2) * R == (1 - d/2) * B, then T = 6500 * (1 + d).
    d = 2.0 * (lin[2] - lin[0]) / max(lin[0] + lin[2], eps)
    lo, hi = _TEMPERATURE_BOUNDS
    suggested = float(min(hi, max(lo, _NEUTRAL_K * (1.0 + d))))
    if rb_ratio > 1.0 + _CAST_THRESHOLD:
        cast = "warm"
    elif rb_ratio < 1.0 - _CAST_THRESHOLD:
        cast = "cool"
    else:
        cast = "neutral"

    mx, mn = peak, rgb.min(axis=2)
    saturation = float(((mx - mn) / np.maximum(mx, eps)).mean())

    import cv2

    lap = cv2.Laplacian((luma * 255.0).astype(np.float32), cv2.CV_32F)
    tilt, confidence = _tilt(luma)

    return ImageReport(
        width=container.width,
        height=container.height,
        luma_mean=round(float(luma.mean()), 3),
        luma_p1=round(p1, 3),
        luma_p5=round(p5, 3),
        luma_p50=round(p50, 3),
        luma_p95=round(p95, 3),
        luma_p99=round(p99, 3),
        clipped_shadow_pct=round(shadow_pct, 2),
        clipped_highlight_pct=round(highlight_pct, 2),
        channel_means=tuple(round(float(v), 3) for v in means),
        cast_rb_ratio=round(rb_ratio, 3),
        cast_label=cast,
        suggested_wb_temperature=round(suggested),
        saturation_mean=round(saturation, 3),
        sharpness=round(float(lap.var()), 1),
        noise_sigma=round(_noise_sigma(rgb_full), 2),
        tilt_deg=None if tilt is None else round(tilt, 2),
        tilt_confidence=None if confidence is None else round(confidence, 2),
        exif=parse_exif(container.metadata.get("exif")),
    )
