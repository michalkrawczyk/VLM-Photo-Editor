from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from vlm_photo_editor.schema.recipe import RECIPE_SCHEMA_VERSION, Recipe

_WB_MIRROR_K = 13000.0  # 2 x the 6500 K neutral point
_WB_BOUNDS_K = (1000.0, 20000.0)  # mirrors PARAM_BOUNDS["temperature"]


def _migrate_recipe_dict(data: dict) -> dict:
    """Upgrade a raw sidecar dict to the current schema (pure; never touches disk).

    v1 -> v2: white_balance flipped direction, so the same look needs the temperature
    mirrored about 6500 K (exact for 1000-12000 K; older values clamp to 1000 K).
    Exposure/WB also moved to linear light, which cannot be migrated — v1 recipes
    replay with the new math.
    """
    if "schema_version" in data:
        return data
    lo, hi = _WB_BOUNDS_K
    for op in (data.get("op_graph") or {}).get("ops", []):
        params = op.get("params") or {}
        if op.get("op_name") == "white_balance" and "temperature" in params:
            mirrored = _WB_MIRROR_K - float(params["temperature"])
            params["temperature"] = min(hi, max(lo, mirrored))
    data["schema_version"] = RECIPE_SCHEMA_VERSION
    return data


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write via a sibling tmp file + os.replace() so a crash mid-write can't
    leave a truncated sidecar that fails validation on next load."""
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


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
        _atomic_write_text(path, recipe.model_dump_json(indent=2))
        return path

    @staticmethod
    def load(sidecar: Path | str) -> Recipe:
        sidecar = Path(sidecar)
        if not sidecar.exists():
            raise FileNotFoundError(f"No sidecar at {sidecar}")
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return Recipe.model_validate(_migrate_recipe_dict(data))

    @staticmethod
    def load_for(source: Path | str, branch: str = "main") -> Recipe:
        return RecipeStore.load(RecipeStore.sidecar_path(source, branch))

    @staticmethod
    def write_xmp(recipe: Recipe) -> None:
        raise NotImplementedError("XMP write deferred to P10")

    @staticmethod
    def read_xmp(xmp_path: Path | str) -> Recipe:
        raise NotImplementedError("XMP read deferred to P10")
