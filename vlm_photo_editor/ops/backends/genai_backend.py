from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op
from vlm_photo_editor.schema.recipe import GenAIOp

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

    prompt = op.params.get("prompt")
    if not prompt:
        raise ValueError(f"Op {op.op_name!r} with GENAI backend requires 'prompt' in params")

    from vlm_photo_editor.config.settings import get_settings

    result, genai_op, _ = run_background_pipeline(
        container,
        mask,
        prompt=prompt,
        model=op.params.get("model") or get_settings().genai_model,
        step_id=op.step_id,
        n_candidates=op.params.get("n", 3),
        seed=op.params.get("seed"),
        **extra_kwargs,
    )
    return result, genai_op
