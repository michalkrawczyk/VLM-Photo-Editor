from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName
from vlm_photo_editor.schema.recipe import GenAIOp

from .mask import bbox_to_mask
from .validator import validate_op_graph


@dataclass
class ExecutionResult:
    container: ImageContainer
    genai_ops: list[GenAIOp] = field(default_factory=list)


class Executor:
    def __init__(self, allowed_ops: set[OpName] | None = None) -> None:
        self._allowed_ops = allowed_ops

    def apply(self, container: ImageContainer, op_graph: OpGraph) -> ExecutionResult:
        validate_op_graph(op_graph, allowed_ops=self._allowed_ops)
        result = container.copy()
        genai_ops: list[GenAIOp] = []
        for op in op_graph.ops:
            result, genai_op = self._apply_op(result, op)
            if genai_op is not None:
                genai_ops.append(genai_op)
        return ExecutionResult(container=result, genai_ops=genai_ops)

    def _apply_op(self, container: ImageContainer, op: Op) -> tuple[ImageContainer, GenAIOp | None]:
        if op.backend == Backend.GENAI:
            from .backends.genai_backend import apply as genai_apply

            result, genai_op = genai_apply(container, op)
            return result, genai_op

        backend_fn = self._resolve_backend(op)

        if op.bbox is None:
            return backend_fn(container, op), None

        # Region-confined: apply to full image then mask to bbox.
        edited = backend_fn(container, op)
        mask = bbox_to_mask(container, op.bbox)
        combined = container.copy()
        combined.pixels = np.where(mask[..., np.newaxis], edited.pixels, container.pixels)
        return combined, None

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
