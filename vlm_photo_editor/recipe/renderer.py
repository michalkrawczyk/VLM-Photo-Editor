from __future__ import annotations

from pathlib import Path

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.imageio.savers import save as _save
from vlm_photo_editor.ops.executor import ExecutionResult, Executor
from vlm_photo_editor.schema.ops import OpGraph, OpName
from vlm_photo_editor.schema.recipe import GenAIOp, Recipe


class Renderer:
    """Deterministic render of a Recipe against an ImageContainer."""

    def __init__(self, allowed_ops: set[OpName] | None = None) -> None:
        self._executor = Executor(allowed_ops=allowed_ops)

    def render(self, recipe: Recipe, container: ImageContainer) -> ExecutionResult:
        graph = self._inject_seeds(recipe.op_graph, recipe.genai_ops)
        return self._executor.apply(container, graph)

    def render_from_path(self, recipe: Recipe) -> ExecutionResult:
        return self.render(recipe, load(Path(recipe.source_path)))

    def apply_as_preset(self, recipe: Recipe, target: ImageContainer) -> ExecutionResult:
        # Preset replay: no stored genai seeds to inject; generate fresh.
        return self._executor.apply(target, recipe.op_graph)

    def render_and_save(
        self,
        recipe: Recipe,
        dest: Path | str,
        fmt: str | None = None,
    ) -> tuple[Path, list[GenAIOp]]:
        result = self.render_from_path(recipe)
        saved_path = _save(result.container, dest, fmt)
        return saved_path, result.genai_ops

    @staticmethod
    def _inject_seeds(op_graph: OpGraph, genai_ops: list[GenAIOp]) -> OpGraph:
        """Pre-populate seed into GENAI op params for deterministic replay."""
        if not genai_ops:
            return op_graph
        seed_map = {g.step_id: g.seed for g in genai_ops}
        ops = [
            (
                op.model_copy(
                    update={"params": {**op.params, "seed": seed_map[op.step_id], "n": 1}}
                )
                if op.step_id in seed_map
                else op
            )
            for op in op_graph.ops
        ]
        return op_graph.model_copy(update={"ops": ops})
