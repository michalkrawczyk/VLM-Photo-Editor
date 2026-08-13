from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op
from vlm_photo_editor.schema.recipe import GenAIOp

if TYPE_CHECKING:
    from vlm_photo_editor.background.quality import GenAISelection, ScoredCandidate

_KNOWN_OP_KEYS = {"prompt", "model", "n", "seed"}


def apply(
    container: ImageContainer,
    op: Op,
    selection: "GenAISelection | None" = None,
) -> tuple[ImageContainer, GenAIOp, list["ScoredCandidate"]]:
    """Route a GENAI op through the background pipeline.

    `selection` replays a prior generation (cached candidates + user's pick) instead
    of calling the provider again.
    """
    from vlm_photo_editor.background import run_background_pipeline
    from vlm_photo_editor.ops.mask import bbox_to_mask

    if op.bbox is not None:
        mask = bbox_to_mask(container, op.bbox)
    else:
        mask = np.ones((container.height, container.width), dtype=bool)

    extra_kwargs = {k: v for k, v in op.params.items() if k not in _KNOWN_OP_KEYS}

    prompt = op.params.get("prompt")
    if not prompt:
        raise ValueError(f"Op {op.op_name!r} with GENAI backend requires 'prompt' in params")

    from vlm_photo_editor.config.settings import get_settings

    result, genai_op, _, scored = run_background_pipeline(
        container,
        mask,
        prompt=prompt,
        model=op.params.get("model") or get_settings().genai_model,
        step_id=op.step_id,
        n_candidates=op.params.get("n", 3),
        seed=op.params.get("seed"),
        candidates=selection.candidates if selection is not None else None,
        override_index=selection.override_index if selection is not None else None,
        **extra_kwargs,
    )
    return result, genai_op, scored
