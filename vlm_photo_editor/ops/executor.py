from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName

from .mask import bbox_to_mask
from .validator import validate_op_graph


class Executor:
    def __init__(self, allowed_ops: set[OpName] | None = None) -> None:
        self._allowed_ops = allowed_ops

    def apply(self, container: ImageContainer, op_graph: OpGraph) -> ImageContainer:
        validate_op_graph(op_graph, allowed_ops=self._allowed_ops)
        result = container.copy()
        for op in op_graph.ops:
            result = self._apply_op(result, op)
        return result

    def _apply_op(self, container: ImageContainer, op: Op) -> ImageContainer:
        backend_fn = self._resolve_backend(op)

        if op.bbox is None:
            return backend_fn(container, op)

        # Region-confined: apply to full image then mask to bbox.
        edited = backend_fn(container, op)
        mask = bbox_to_mask(container, op.bbox)
        combined = container.copy()
        combined.pixels = np.where(mask[..., np.newaxis], edited.pixels, container.pixels)
        return combined

    @staticmethod
    def _resolve_backend(op: Op):
        if op.backend == Backend.PIL:
            from .backends.pil_backend import apply
            return apply
        if op.backend == Backend.OPENCV:
            from .backends.cv_backend import apply
            return apply
        from .backends.stubs import apply
        return apply
