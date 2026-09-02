from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .providers import GenAIProvider, get_provider
from .providers.base import Candidate
from .quality import ScoredCandidate, select_best


def run_background_pipeline(
    container: ImageContainer,
    mask: np.ndarray,
    prompt: str,
    model: str,
    step_id: str,
    n_candidates: int = 3,
    seed: int | None = None,
    threshold: float | None = None,
    provider: GenAIProvider | None = None,
    feather_px: int | None = None,
    candidates: list[Candidate] | None = None,
    override_index: int | None = None,
    **kwargs,
) -> tuple[ImageContainer, GenAIOp, bool, list[ScoredCandidate]]:
    """Generate, composite, and gate N background candidates.

    Returns (best_composited, genai_op, needs_manual_review, scored_candidates).
    provider defaults to get_provider(model) when None.
    Pass `candidates` to re-use an earlier generation (no provider call) and
    `override_index` to take that entry of the scored list instead of the best.
    """
    if candidates is None:
        if provider is None:
            provider = get_provider(model)
        candidates = provider.generate(
            container,
            mask,
            prompt=prompt,
            model=model,
            step_id=step_id,
            n=n_candidates,
            seed=seed,
            **kwargs,
        )

    selection = select_best(
        source=container,
        candidates=candidates,
        mask=mask,
        threshold=threshold,
        provider=provider,
        feather_px=feather_px,
        override_index=override_index,
    )
    return (
        selection.best_composite,
        selection.best_candidate.genai_op,
        selection.needs_manual,
        selection.scored,
    )
