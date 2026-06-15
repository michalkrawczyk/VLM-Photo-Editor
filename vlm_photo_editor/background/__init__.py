from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .generator import Candidate, Generator
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
    generator: Generator | None = None,
    feather_px: int = 20,
    **kwargs,
) -> tuple[ImageContainer, GenAIOp, bool]:
    """Generate, composite, and gate N background candidates.

    Returns (best_composited, genai_op, needs_manual_review).
    """
    if generator is None:
        generator = Generator()

    candidates: list[Candidate] = generator.generate(
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
        generator=generator,
        feather_px=feather_px,
    )
    return best_comp, best_cand.genai_op, needs_manual
