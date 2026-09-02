from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion
from skimage.filters import sobel

from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.imageio.container import ImageContainer

from .composite import composite
from .providers.base import Candidate, GenAIProvider


@dataclass
class ScoredCandidate:
    """A candidate composited against the source and scored by `seam_metric`."""

    metric: float
    composite: ImageContainer
    candidate: Candidate


@dataclass
class GenAISelection:
    """A prior generation replayed for one step: reuse `candidates`, pick `override_index`."""

    candidates: list[Candidate]
    override_index: int | None = None


@dataclass
class BackgroundSelection:
    """Outcome of `select_best`: the pick, the gate flag, and every scored candidate."""

    best_composite: ImageContainer
    best_candidate: Candidate
    needs_manual: bool
    scored: list[ScoredCandidate]


def seam_metric(composited: ImageContainer, mask: np.ndarray) -> float:
    """Mean absolute gradient discontinuity at the mask boundary.

    Lower is better. Computed on a 2px ring on each side of the boundary.
    """
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
    threshold: float | None = None,
    extra_seeds: int = 2,
    provider: GenAIProvider | None = None,
    feather_px: int | None = None,
    override_index: int | None = None,
) -> BackgroundSelection:
    """Pick the candidate with the lowest seam metric.

    If no candidate passes threshold:
      - Roll extra_seeds more via generator (if provided)
      - Flag the result for manual review

    `override_index` selects that entry of the scored list instead — a user choice
    wins over the metric, and neither the gate nor the re-roll runs.
    """
    if not candidates:
        raise ValueError("select_best requires at least one candidate")
    if threshold is None:
        threshold = get_settings().seam_threshold

    def _evaluate(cands: list[Candidate]) -> list[ScoredCandidate]:
        results = []
        for c in cands:
            comp = composite(source, c.container, mask, feather_px=feather_px)
            results.append(ScoredCandidate(seam_metric(comp, mask), comp, c))
        return results

    scored = _evaluate(candidates)
    scored.sort(key=lambda s: s.metric)

    if override_index is not None:
        picked = scored[override_index]
        return BackgroundSelection(picked.composite, picked.candidate, False, scored)

    best = scored[0]

    if best.metric < threshold:
        return BackgroundSelection(best.composite, best.candidate, False, scored)

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
        if extra_scored:
            scored = sorted(scored + extra_scored, key=lambda s: s.metric)
            best = scored[0]
        if best.metric < threshold:
            return BackgroundSelection(best.composite, best.candidate, False, scored)

    # Still failing — flag for manual review
    return BackgroundSelection(best.composite, best.candidate, True, scored)
