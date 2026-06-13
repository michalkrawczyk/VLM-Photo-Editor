from __future__ import annotations

import json
from pathlib import Path

from vlm_photo_editor.schema.recipe import Recipe


class RecipeStore:
    """Serialize/deserialize Recipe to/from a sidecar .edit.json file.

    Sidecar naming:
        branch="main"  → <stem>.edit.json
        branch="v2"    → <stem>.v2.edit.json
    """

    @staticmethod
    def sidecar_path(source: Path | str, branch: str = "main") -> Path:
        source = Path(source)
        if branch == "main":
            name = source.stem + ".edit.json"
        else:
            name = f"{source.stem}.{branch}.edit.json"
        return source.parent / name

    @staticmethod
    def save(recipe: Recipe, directory: Path | str | None = None) -> Path:
        if not recipe.source_path:
            raise ValueError("recipe.source_path must not be empty")
        dest_dir = Path(directory) if directory is not None else Path(recipe.source_path).parent
        path = dest_dir / RecipeStore.sidecar_path(recipe.source_path, recipe.branch).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load(sidecar: Path | str) -> Recipe:
        sidecar = Path(sidecar)
        if not sidecar.exists():
            raise FileNotFoundError(f"No sidecar at {sidecar}")
        return Recipe.model_validate(json.loads(sidecar.read_text(encoding="utf-8")))

    @staticmethod
    def load_for(source: Path | str, branch: str = "main") -> Recipe:
        return RecipeStore.load(RecipeStore.sidecar_path(source, branch))

    @staticmethod
    def write_xmp(recipe: Recipe) -> None:
        raise NotImplementedError("XMP write deferred to P10")

    @staticmethod
    def read_xmp(xmp_path: Path | str) -> Recipe:
        raise NotImplementedError("XMP read deferred to P10")
