from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op
from vlm_photo_editor.schema.recipe import GenAIOp

_DEFAULT_MODEL = "black-forest-labs/flux-fill-dev"
_KNOWN_OP_KEYS = {"prompt", "model", "n", "seed"}


def apply(container: ImageContainer, op: Op) -> tuple[ImageContainer, GenAIOp]:
    """Route a GENAI op through the background pipeline."""
    from vlm_photo_editor.background import run_background_pipeline
    from vlm_photo_editor.ops.mask import bbox_to_mask

    if op.bbox is not None:
        mask = bbox_to_mask(container, op.bbox)
    else:
        mask = np.ones((container.height, container.width), dtype=bool)

    extra_kwargs = {k: v for k, v in op.params.items() if k not in _KNOWN_OP_KEYS}

    result, genai_op, _ = run_background_pipeline(
        container,
        mask,
        prompt=op.params["prompt"],
        model=op.params.get("model", _DEFAULT_MODEL),
        step_id=op.step_id,
        n_candidates=op.params.get("n", 3),
        seed=op.params.get("seed"),
        **extra_kwargs,
    )
    return result, genai_op
