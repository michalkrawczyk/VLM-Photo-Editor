from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .providers import GenAIProvider, get_provider
from .providers.base import Candidate
from .quality import select_best


def run_background_pipeline(
    container: ImageContainer,
    mask: np.ndarray,
    prompt: str,
    model: str,
    step_id: str,
    n_candidates: int = 3,
    seed: int | None = None,
    threshold: float = 10.0,
    provider: GenAIProvider | None = None,
    feather_px: int = 20,
    **kwargs,
) -> tuple[ImageContainer, GenAIOp, bool]:
    """Generate, composite, and gate N background candidates.

    Returns (best_composited, genai_op, needs_manual_review).
    provider defaults to get_provider(model) when None.
    """
    if provider is None:
        provider = get_provider(model)

    candidates: list[Candidate] = provider.generate(
        container,
        mask,
        prompt=prompt,
        model=model,
        step_id=step_id,
        n=n_candidates,
        seed=seed,
        **kwargs,
    )

    best_comp, best_cand, needs_manual = select_best(
        source=container,
        candidates=candidates,
        mask=mask,
        threshold=threshold,
        provider=provider,
        feather_px=feather_px,
    )
    return best_comp, best_cand.genai_op, needs_manual
