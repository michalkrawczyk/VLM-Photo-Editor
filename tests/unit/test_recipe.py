from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.recipe import RecipeStore, Renderer, UndoStack
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName
from vlm_photo_editor.schema.recipe import Recipe

_FAKE_SRC = Path("/fake/source.jpg")


def _make_png(path: Path, value: int = 64, size: tuple[int, int] = (32, 32)) -> np.ndarray:
    pixels = np.full((*size, 3), value, dtype=np.uint8)
    Image.fromarray(pixels, "RGB").save(path, format="PNG")
    return pixels


def _op(ev: float = 1.0) -> Op:
    return Op(op_name=OpName.EXPOSURE, params={"ev": ev}, backend=Backend.PIL, step_id="s1")


def _make_recipe(source_path: Path | str, *, ev: float = 1.0, branch: str = "main") -> Recipe:
    return Recipe(
        source_path=str(source_path),
        op_graph=OpGraph(ops=[_op(ev)]),
        branch=branch,
    )


def _make_container(value: int = 64) -> ImageContainer:
    pixels = np.full((32, 32, 3), value, dtype=np.uint8)
    return ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)


# ---------------------------------------------------------------------------
# Store — sidecar path naming
# ---------------------------------------------------------------------------


def test_store_sidecar_path_naming() -> None:
    src = Path("/photos/sunset.jpg")

    main_path = RecipeStore.sidecar_path(src, "main")
    assert main_path == Path("/photos/sunset.edit.json")

    v2_path = RecipeStore.sidecar_path(src, "v2")
    assert v2_path == Path("/photos/sunset.v2.edit.json")

    custom_path = RecipeStore.sidecar_path(src, "warm-tone")
    assert custom_path == Path("/photos/sunset.warm-tone.edit.json")


# ---------------------------------------------------------------------------
# Store — save / load round-trip
# ---------------------------------------------------------------------------


def test_store_save_and_load_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "photo.jpg"
    src.touch()
    recipe = _make_recipe(src)

    saved_path = RecipeStore.save(recipe)
    assert saved_path.exists()
    assert saved_path.name == "photo.edit.json"

    loaded = RecipeStore.load(saved_path)
    assert loaded.recipe_id == recipe.recipe_id
    assert loaded.source_path == recipe.source_path
    assert loaded.branch == "main"
    assert loaded.op_graph.ops[0].op_name == OpName.EXPOSURE

    loaded_via_for = RecipeStore.load_for(src)
    assert loaded_via_for.recipe_id == recipe.recipe_id


def _wb_recipe_json(temperature: float, *, with_version: bool) -> str:
    recipe = Recipe(
        source_path="photo.jpg",
        op_graph=OpGraph(
            ops=[
                Op(
                    op_name=OpName.WHITE_BALANCE,
                    params={"temperature": temperature},
                    backend=Backend.PIL,
                    step_id="s1",
                )
            ]
        ),
    )
    data = json.loads(recipe.model_dump_json())
    if not with_version:
        del data["schema_version"]  # what every pre-v2 sidecar on disk looks like
    return json.dumps(data)


@pytest.mark.parametrize(
    "stored,with_version,expected",
    [
        (4000.0, False, 9000.0),  # v1 "cooler" 4000 K  -> same look as v2 9000 K
        (6500.0, False, 6500.0),  # neutral is its own mirror
        (15000.0, False, 1000.0),  # old extreme-blue values clamp to the lower bound
        (4000.0, True, 4000.0),  # v2 sidecar is untouched
    ],
)
def test_store_load_migrates_v1_white_balance(
    tmp_path: Path, stored: float, with_version: bool, expected: float
) -> None:
    sidecar = tmp_path / "photo.edit.json"
    sidecar.write_text(_wb_recipe_json(stored, with_version=with_version), encoding="utf-8")

    loaded = RecipeStore.load(sidecar)

    assert loaded.schema_version == 2
    assert loaded.op_graph.ops[0].params["temperature"] == expected
    # Migration is in-memory only: the file on disk is not rewritten by load().
    assert ("schema_version" in json.loads(sidecar.read_text())) is with_version


def test_store_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        RecipeStore.load(tmp_path / "nonexistent.edit.json")


def test_store_branch_creates_separate_sidecars(tmp_path: Path) -> None:
    src = tmp_path / "photo.jpg"
    src.touch()

    main_recipe = _make_recipe(src, ev=1.0, branch="main")
    v2_recipe = _make_recipe(src, ev=2.0, branch="v2")

    main_path = RecipeStore.save(main_recipe)
    v2_path = RecipeStore.save(v2_recipe)

    assert main_path != v2_path
    assert main_path.exists() and v2_path.exists()

    assert RecipeStore.load(main_path).branch == "main"
    assert RecipeStore.load(v2_path).branch == "v2"
    assert RecipeStore.load(v2_path).op_graph.ops[0].params["ev"] == 2.0


def test_store_save_atomic_on_write_failure(tmp_path: Path, monkeypatch) -> None:
    """A crash mid-write must not corrupt a previously-saved sidecar."""
    src = tmp_path / "photo.jpg"
    src.touch()
    saved_path = RecipeStore.save(_make_recipe(src, ev=1.0))
    original_bytes = saved_path.read_bytes()

    def _crash_partway(self, data, *args, **kwargs):
        with open(self, "w", encoding="utf-8") as f:
            f.write(data[: len(data) // 2])
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(Path, "write_text", _crash_partway)
    with pytest.raises(OSError):
        RecipeStore.save(_make_recipe(src, ev=2.0))

    assert saved_path.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*.tmp"))


def test_xmp_stubs_raise(tmp_path: Path) -> None:
    recipe = _make_recipe(tmp_path / "photo.jpg")
    with pytest.raises(NotImplementedError, match="deferred"):
        RecipeStore.write_xmp(recipe)
    with pytest.raises(NotImplementedError, match="deferred"):
        RecipeStore.read_xmp(tmp_path / "photo.xmp")


# ---------------------------------------------------------------------------
# Renderer — determinism and source immutability
# ---------------------------------------------------------------------------


def test_render_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _make_png(src)
    recipe = _make_recipe(src)
    renderer = Renderer()

    result1 = renderer.render_from_path(recipe)
    result2 = renderer.render_from_path(recipe)

    np.testing.assert_array_equal(result1.container.pixels, result2.container.pixels)


def test_render_source_unchanged(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _make_png(src)
    original_bytes = src.read_bytes()

    recipe = _make_recipe(src)
    Renderer().render_from_path(recipe)

    assert src.read_bytes() == original_bytes


def test_render_and_save_refuses_source_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _make_png(src)
    recipe = _make_recipe(src)

    with pytest.raises(ValueError, match="Cannot overwrite source"):
        Renderer().render_and_save(recipe, dest=src)


def test_render_applies_ops(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _make_png(src, value=64)
    recipe = _make_recipe(src, ev=1.0)

    result = Renderer().render_from_path(recipe)

    # ev=1.0 doubles LINEAR light: sRGB code 64 -> ~90 (not 128, which was the gamma-space math)
    np.testing.assert_allclose(result.container.pixels, 90, atol=1)


# ---------------------------------------------------------------------------
# Renderer — preset reapply
# ---------------------------------------------------------------------------


def test_preset_reapply(tmp_path: Path) -> None:
    src_a = tmp_path / "source_a.png"
    src_b = tmp_path / "source_b.png"
    _make_png(src_a, value=64)
    _make_png(src_b, value=32)

    recipe = _make_recipe(src_a, ev=1.0)
    renderer = Renderer()

    result_b = renderer.apply_as_preset(recipe, load(src_b))

    # src_b starts at 32; ev=1.0 doubles linear light -> ~47
    np.testing.assert_allclose(result_b.container.pixels, 47, atol=1)
    # different from src_a result (~90) and from raw src_b pixels (32)
    assert result_b.container.pixels[0, 0, 0] != 32
    assert result_b.container.pixels[0, 0, 0] != 90


# ---------------------------------------------------------------------------
# UndoStack — undo / redo
# ---------------------------------------------------------------------------


def test_undo_restores_prior_state() -> None:
    recipe_a = _make_recipe(_FAKE_SRC, ev=1.0)
    recipe_b = _make_recipe(_FAKE_SRC, ev=2.0)

    stack = UndoStack(recipe_a)
    stack.push(recipe_b)

    assert stack.current.op_graph.ops[0].params["ev"] == 2.0
    assert stack.can_undo

    restored = stack.undo()
    assert restored.op_graph.ops[0].params["ev"] == 1.0
    assert stack.can_redo
    assert not stack.can_undo


def test_undo_raises_at_bottom() -> None:
    stack = UndoStack(_make_recipe(_FAKE_SRC))
    with pytest.raises(IndexError):
        stack.undo()


def test_redo_and_push_discards_future() -> None:
    recipe_a = _make_recipe(_FAKE_SRC, ev=1.0)
    recipe_b = _make_recipe(_FAKE_SRC, ev=2.0)
    recipe_c = _make_recipe(_FAKE_SRC, ev=3.0)
    recipe_d = _make_recipe(_FAKE_SRC, ev=4.0)

    stack = UndoStack(recipe_a)
    stack.push(recipe_b)
    stack.push(recipe_c)
    stack.undo()
    stack.undo()
    # back to recipe_a; push recipe_d — discards b and c
    stack.push(recipe_d)

    assert not stack.can_redo
    assert stack.current.op_graph.ops[0].params["ev"] == 4.0
    assert len(stack) == 2  # a + d


def test_redo_raises_at_tip() -> None:
    stack = UndoStack(_make_recipe(_FAKE_SRC))
    with pytest.raises(IndexError):
        stack.redo()


def test_stack_isolates_mutations() -> None:
    recipe = _make_recipe(_FAKE_SRC, ev=1.0)
    stack = UndoStack(recipe)

    # mutating the original recipe after push must not affect the stack
    recipe.op_graph.ops[0].params["ev"] = 99.0
    assert stack.current.op_graph.ops[0].params["ev"] == 1.0


# ---------------------------------------------------------------------------
# Schema — branch field
# ---------------------------------------------------------------------------


def test_recipe_branch_default_and_round_trip() -> None:
    recipe = Recipe(source_path="x.jpg", op_graph=OpGraph())
    assert recipe.branch == "main"

    dumped = recipe.model_dump()
    assert dumped["branch"] == "main"

    restored = Recipe.model_validate(dumped)
    assert restored.branch == "main"
    assert restored.recipe_id == recipe.recipe_id
