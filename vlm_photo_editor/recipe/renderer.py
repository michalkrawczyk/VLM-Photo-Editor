from __future__ import annotations

from pathlib import Path

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.imageio.savers import save as _save
from vlm_photo_editor.ops.executor import Executor
from vlm_photo_editor.schema.ops import OpName
from vlm_photo_editor.schema.recipe import Recipe


class Renderer:
    """Deterministic render of a Recipe against an ImageContainer."""

    def __init__(self, allowed_ops: set[OpName] | None = None) -> None:
        self._executor = Executor(allowed_ops=allowed_ops)

    def render(self, recipe: Recipe, container: ImageContainer) -> ImageContainer:
        return self._executor.apply(container, recipe.op_graph)

    def render_from_path(self, recipe: Recipe) -> ImageContainer:
        return self.render(recipe, load(Path(recipe.source_path)))

    def apply_as_preset(self, recipe: Recipe, target: ImageContainer) -> ImageContainer:
        return self.render(recipe, target)

    def render_and_save(
        self,
        recipe: Recipe,
        dest: Path | str,
        fmt: str | None = None,
    ) -> Path:
        result = self.render_from_path(recipe)
        return _save(result, dest, fmt)
