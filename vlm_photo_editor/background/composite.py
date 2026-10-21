from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation, distance_transform_edt, gaussian_filter, uniform_filter
from skimage.color import lab2rgb, rgb2lab

from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.imageio.container import ImageContainer


def _to_float(container: ImageContainer) -> np.ndarray:
    """Normalize pixels to [0, 1] float64."""
    maxval = 65535.0 if container.bit_depth == 16 else 255.0
    return container.pixels.astype(np.float64) / maxval


def _from_float(arr: np.ndarray, source: ImageContainer) -> ImageContainer:
    maxval = 65535.0 if source.bit_depth == 16 else 255.0
    dtype = np.uint16 if source.bit_depth == 16 else np.uint8
    pixels = np.clip(arr * maxval, 0, maxval).astype(dtype)
    result = source.copy()
    result.pixels = pixels
    return result


def _border_ring(mask: np.ndarray, dilation_px: int = 5) -> np.ndarray:
    """Return bool mask of pixels just outside the fill region (border ring)."""
    dilated = binary_dilation(mask, iterations=dilation_px)
    return dilated & ~mask


def _feather_zone(mask: np.ndarray, feather_px: int) -> np.ndarray:
    """Pixels the feather may touch: within 3 sigma (Euclidean) of the mask.

    Beyond it the blend alpha is forced to 0, so everything outside is source by construction.
    """
    return distance_transform_edt(~mask) <= 3 * feather_px


def color_match(
    source: ImageContainer,
    generated: ImageContainer,
    mask: np.ndarray,
) -> ImageContainer:
    """LAB mean/std transfer from the border ring of source to the generated region."""
    src_f = _to_float(source)
    gen_f = _to_float(generated)

    ring = _border_ring(mask)

    src_lab = rgb2lab(src_f)
    ring_pixels = src_lab[ring]
    if ring_pixels.shape[0] == 0:
        return generated.copy()
    src_mean = ring_pixels.mean(axis=0)
    src_std = ring_pixels.std(axis=0) + 1e-6

    gen_lab = rgb2lab(gen_f)
    gen_pixels = gen_lab[mask]
    gen_mean = gen_pixels.mean(axis=0)
    gen_std = gen_pixels.std(axis=0) + 1e-6

    out_lab = gen_lab.copy()
    out_lab[mask] = (gen_lab[mask] - gen_mean) / gen_std * src_std + src_mean

    out_rgb = lab2rgb(out_lab)
    result = _from_float(out_rgb, generated)
    # Restore outside-mask pixels exactly — LAB roundtrip introduces float drift on quantization.
    result.pixels[~mask] = generated.pixels[~mask]
    return result


def grain_match(
    source: ImageContainer,
    generated: ImageContainer,
    mask: np.ndarray,
) -> ImageContainer:
    """Match grain/noise level of source to the generated region."""
    src_f = _to_float(source)
    gen_f = _to_float(generated)

    def noise_std(arr: np.ndarray, m: np.ndarray) -> float:
        smoothed = uniform_filter(arr, size=3)
        residual = arr[m] - smoothed[m]
        return float(np.std(residual)) + 1e-9

    src_noise = noise_std(src_f, mask)
    gen_noise = noise_std(gen_f, mask)

    ratio = src_noise / gen_noise
    smoothed_gen = uniform_filter(gen_f, size=3)
    gen_noise_layer = gen_f - smoothed_gen

    out_f = gen_f.copy()
    out_f[mask] = smoothed_gen[mask] + gen_noise_layer[mask] * ratio

    result = _from_float(out_f, generated)
    # Restore outside-mask pixels exactly — float arithmetic introduces quantization drift.
    result.pixels[~mask] = generated.pixels[~mask]
    return result


def seam_blend(
    source: ImageContainer,
    generated: ImageContainer,
    mask: np.ndarray,
    feather_px: int | None = None,
) -> ImageContainer:
    """Feathered Gaussian blend at the mask boundary."""
    if feather_px is None:
        feather_px = get_settings().feather_px
    src_f = _to_float(source)
    gen_f = _to_float(generated)

    # BG-B1: a Gaussian has unbounded support; truncate the ramp at the feather zone
    # so the "outside is untouched" invariant holds exactly, not approximately.
    zone = _feather_zone(mask, feather_px)
    alpha = np.where(zone, gaussian_filter(mask.astype(np.float64), sigma=feather_px), 0.0)
    alpha = alpha[..., np.newaxis]

    blended = alpha * gen_f + (1.0 - alpha) * src_f
    result = _from_float(blended, source)
    # The float round-trip can land a level off; outside the zone the source wins outright.
    result.pixels[~zone] = source.pixels[~zone]
    return result


def composite(
    source: ImageContainer,
    generated: ImageContainer,
    mask: np.ndarray,
    feather_px: int | None = None,
) -> ImageContainer:
    """Full pipeline: color_match → grain_match → seam_blend.

    Pixels outside the feather zone are byte-identical to source by construction
    (`seam_blend` zeroes the alpha ramp there and copies source through).
    """
    if feather_px is None:
        feather_px = get_settings().feather_px
    matched = color_match(source, generated, mask)
    matched = grain_match(source, matched, mask)
    return seam_blend(source, matched, mask, feather_px=feather_px)
