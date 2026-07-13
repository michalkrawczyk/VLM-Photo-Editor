from __future__ import annotations

import numpy as np
from skimage.filters import sobel

from vlm_photo_editor.imageio.container import ImageContainer

from .composite import composite
from .providers.base import Candidate, GenAIProvider


def seam_metric(composited: ImageContainer, mask: np.ndarray) -> float:
    """Mean absolute gradient discontinuity at the mask boundary.

    Lower is better. Computed on a 2px ring on each side of the boundary.
    """
    from scipy.ndimage import binary_dilation, binary_erosion

    pixels = composited.pixels.astype(np.float64)
    if composited.bit_depth == 16:
        pixels /= 65535.0
    else:
        pixels /= 255.0

    # Gradient magnitude (mean over channels)
    grad = np.mean([sobel(pixels[..., c]) for c in range(pixels.shape[2])], axis=0)

    # 2px ring just inside the mask boundary
    inner_ring = mask & ~binary_erosion(mask, iterations=2)
    # 2px ring just outside the mask boundary
    outer_ring = binary_dilation(mask, iterations=2) & ~mask

    if inner_ring.sum() == 0 or outer_ring.sum() == 0:
        return 0.0

    return float(np.mean(np.abs(grad[inner_ring].mean() - grad[outer_ring].mean())))


def select_best(
    source: ImageContainer,
    candidates: list[Candidate],
    mask: np.ndarray,
    threshold: float = 10.0,
    extra_seeds: int = 2,
    provider: GenAIProvider | None = None,
    feather_px: int = 20,
) -> tuple[ImageContainer, Candidate, bool]:
    """Pick the candidate with the lowest seam metric.

    If no candidate passes threshold:
      - Roll extra_seeds more via generator (if provided)
      - Return (best_composite, best_candidate, needs_manual)
    """

    def _evaluate(cands: list[Candidate]) -> list[tuple[float, ImageContainer, Candidate]]:
        results = []
        for c in cands:
            comp = composite(source, c.container, mask, feather_px=feather_px)
            metric = seam_metric(comp, mask)
            results.append((metric, comp, c))
        return results

    scored = _evaluate(candidates)
    scored.sort(key=lambda t: t[0])
    best_metric, best_comp, best_cand = scored[0]

    if best_metric < threshold:
        return best_comp, best_cand, False

    # Threshold not met; try extra seeds if a provider is available
    if provider is not None and extra_seeds > 0:
        first = candidates[0]
        extras = provider.generate(
            source,
            mask,
            prompt=first.genai_op.prompt,
            model=first.genai_op.model,
            step_id=first.genai_op.step_id,
            n=extra_seeds,
        )
        extra_scored = _evaluate(extras)
        extra_scored.sort(key=lambda t: t[0])
        if extra_scored[0][0] < best_metric:
            best_metric, best_comp, best_cand = extra_scored[0]
        if best_metric < threshold:
            return best_comp, best_cand, False

    # Still failing — flag for manual review
    return best_comp, best_cand, True
