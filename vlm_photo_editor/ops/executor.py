from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Backend, BoundingBox, Op, OpGraph, OpName
from vlm_photo_editor.schema.recipe import GenAIOp

from .constants import INPAINT_OPS as _INPAINT_OPS
from .mask import bbox_to_mask
from .validator import validate_op_graph

if TYPE_CHECKING:
    from vlm_photo_editor.background.quality import GenAISelection, ScoredCandidate

# Offset of the current working image's top-left corner within the image the plan
# started from. None once a ROTATE has made that offset un-trackable.
Origin = tuple[int, int] | None


@dataclass
class ExecutionResult:
    container: ImageContainer
    genai_ops: list[GenAIOp] = field(default_factory=list)
    # step_id → every candidate scored for that genAI step (best first).
    genai_candidates: dict[str, list["ScoredCandidate"]] = field(default_factory=dict)
    # step_ids of genAI steps whose result failed the seam gate and need manual review.
    genai_needs_manual: list[str] = field(default_factory=list)


class Executor:
    def __init__(self, allowed_ops: set[OpName] | None = None) -> None:
        self._allowed_ops = allowed_ops

    def apply(
        self,
        container: ImageContainer,
        op_graph: OpGraph,
        genai_selection: "dict[str, GenAISelection] | None" = None,
    ) -> ExecutionResult:
        """Run the graph. `genai_selection` (step_id → prior candidates + user pick)
        replays genAI steps from cache instead of calling the provider again."""
        validate_op_graph(op_graph, allowed_ops=self._allowed_ops, require_bbox=True)
        result = container.copy()
        genai_ops: list[GenAIOp] = []
        candidates: dict[str, list[ScoredCandidate]] = {}
        needs_manual: list[str] = []
        origin: Origin = (0, 0)
        start_size = (container.width, container.height)
        for op in op_graph.ops:
            h, w = result.pixels.shape[:2]
            op = self._remap_for_origin(op, origin, (w, h), (w, h) != start_size)
            selection = (genai_selection or {}).get(op.step_id)
            result, genai_op, scored, flagged = self._apply_op(result, op, selection)
            origin = self._advance_origin(op, origin, w, h)
            if genai_op is not None:
                genai_ops.append(genai_op)
            if scored:
                candidates[op.step_id] = scored
            if flagged:
                needs_manual.append(op.step_id)
        return ExecutionResult(
            container=result,
            genai_ops=genai_ops,
            genai_candidates=candidates,
            genai_needs_manual=needs_manual,
        )

    @staticmethod
    def _remap_for_origin(
        op: Op, origin: Origin, size: tuple[int, int], resized: bool = False
    ) -> Op:
        """Shift op.bbox / FRAME focus_* / CROP bounds from plan-start coordinates into
        the current (possibly already cropped) image's coordinate space.

        `size` is the working image's (width, height). `resized`: it is no longer the
        plan-start size, so CROP bounds are also clamped to it (they were validated
        against the original dimensions).
        """
        has_focus = op.op_name == OpName.FRAME and all(
            k in op.params for k in ("focus_x", "focus_y", "focus_w", "focus_h")
        )

        if origin is None:
            if op.bbox is not None or has_focus:
                raise ValueError(
                    "Cannot confine an edit to a region after a ROTATE op; region/focus "
                    "coordinates cannot be remapped through a rotation."
                )
            return op

        ox, oy = origin
        if op.op_name == OpName.CROP and (origin != (0, 0) or resized):
            op = Executor._remap_crop(op, ox, oy, *size)

        if origin == (0, 0):
            return op

        if op.bbox is not None:
            x = op.bbox.x - ox
            y = op.bbox.y - oy
            x2 = x + op.bbox.width
            y2 = y + op.bbox.height
            x_clamped = max(0, x)
            y_clamped = max(0, y)
            if x2 <= x_clamped or y2 <= y_clamped:
                raise ValueError(
                    "Region selection falls outside the cropped image; adjust the "
                    "selection or reorder the plan."
                )
            op = op.model_copy(
                update={
                    "bbox": BoundingBox(
                        x=x_clamped,
                        y=y_clamped,
                        width=x2 - x_clamped,
                        height=y2 - y_clamped,
                    )
                }
            )

        if has_focus:
            op = op.model_copy(
                update={
                    "params": {
                        **op.params,
                        "focus_x": float(op.params["focus_x"]) - ox,
                        "focus_y": float(op.params["focus_y"]) - oy,
                    }
                }
            )
        return op

    @staticmethod
    def _remap_crop(op: Op, ox: int, oy: int, w: int, h: int) -> Op:
        """OE-B1: CROP bounds are plan-start coordinates like bbox; shift them into the
        current image and clamp to it."""
        left = max(0, int(op.params["left"]) - ox)
        top = max(0, int(op.params["top"]) - oy)
        right = min(w, int(op.params["right"]) - ox)
        bottom = min(h, int(op.params["bottom"]) - oy)
        if right <= left or bottom <= top:
            raise ValueError(
                "Crop region falls outside the already-cropped image; adjust the "
                "crop or reorder the plan."
            )
        return op.model_copy(
            update={
                "params": {**op.params, "left": left, "top": top, "right": right, "bottom": bottom}
            }
        )

    @staticmethod
    def _advance_origin(op: Op, origin: Origin, w: int, h: int) -> Origin:
        """Update the accumulated origin after `op` ran, given the container's
        width/height (`w`, `h`) before `op` ran."""
        if origin is None:
            return None
        if op.op_name == OpName.ROTATE:
            return None
        if op.op_name == OpName.CROP:
            ox, oy = origin
            return ox + int(op.params["left"]), oy + int(op.params["top"])
        if op.op_name == OpName.FRAME:
            from .backends.pil_backend import frame_crop_box

            mode = str(op.params.get("mode", "rule_of_thirds"))
            box = frame_crop_box(w, h, mode, op.params)
            if box is None:
                return origin
            left, top, _, _ = box
            ox, oy = origin
            return ox + left, oy + top
        return origin

    def _apply_op(
        self, container: ImageContainer, op: Op, selection: "GenAISelection | None" = None
    ) -> tuple[ImageContainer, GenAIOp | None, list["ScoredCandidate"], bool]:
        if op.backend == Backend.GENAI:
            from .backends.genai_backend import apply as genai_apply

            return genai_apply(container, op, selection)

        if op.backend == Backend.OPENCV and op.op_name in _INPAINT_OPS:
            if op.op_name == OpName.REGION_EDIT and op.params.get("method") == "blur":
                from .backends.cv_backend import apply_blur

                return apply_blur(container, op), None, [], False

            from .backends.cv_backend import apply_inpaint

            return apply_inpaint(container, op), None, [], False

        if op.backend == Backend.PHOTOSHOP and op.op_name in _INPAINT_OPS:
            from .backends.stubs import apply as stub_apply

            return stub_apply(container, op), None, [], False

        backend_fn = self._resolve_backend(op)

        if op.bbox is None:
            return backend_fn(container, op), None, [], False

        # Region-confined: apply to full image then mask to bbox.
        edited = backend_fn(container, op)
        if edited.pixels.dtype != container.pixels.dtype:
            if container.pixels.dtype == np.uint16 and edited.pixels.dtype == np.uint8:
                edited = edited.copy()
                edited.pixels = edited.pixels.astype(np.uint16) * 257  # exact 0-255 -> 0-65535
            else:
                raise ValueError(
                    f"{op.op_name} backend returned dtype {edited.pixels.dtype}, "
                    f"expected {container.pixels.dtype}; cannot safely composite region"
                )
        mask = bbox_to_mask(container, op.bbox)
        if op.params.get("invert", False):
            mask = ~mask
        combined = container.copy()
        combined.pixels = np.where(mask[..., np.newaxis], edited.pixels, container.pixels)
        return combined, None, [], False

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
