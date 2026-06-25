from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.ops.executor import Executor
from vlm_photo_editor.ops.mask import bbox_to_mask
from vlm_photo_editor.ops.validator import validate_op, validate_op_graph
from vlm_photo_editor.schema.ops import Backend, BoundingBox, Op, OpGraph, OpName

_FAKE_SRC = Path("/fake/source.jpg")


def _container(pixels: np.ndarray | None = None, bit_depth: int = 8) -> ImageContainer:
    if pixels is None:
        pixels = np.full((64, 64, 3), 128, dtype=np.uint8)
    return ImageContainer(pixels=pixels, bit_depth=bit_depth, source_path=_FAKE_SRC)


def _op(
    name: OpName, params: dict, *, bbox: BoundingBox | None = None, backend: Backend = Backend.PIL
) -> Op:
    return Op(op_name=name, params=params, bbox=bbox, backend=backend, step_id="s1")


def _graph(*ops: Op) -> OpGraph:
    return OpGraph(ops=list(ops))


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,params",
    [
        (OpName.CROP, {"left": 0, "top": 0}),  # missing right + bottom
        (OpName.ROTATE, {}),  # missing angle
        (OpName.WHITE_BALANCE, {}),  # missing temperature
        (OpName.EXPOSURE, {}),  # missing ev
    ],
)
def test_validator_rejects_missing_param(op_name: OpName, params: dict) -> None:
    op = Op(op_name=op_name, params=params, step_id="s1")
    with pytest.raises(ValueError, match="missing required param"):
        validate_op(op)


@pytest.mark.parametrize(
    "op_name,params",
    [
        (OpName.EXPOSURE, {"ev": -11.0}),
        (OpName.EXPOSURE, {"ev": 11.0}),
        (OpName.ROTATE, {"angle": 400.0}),
        (OpName.WHITE_BALANCE, {"temperature": 500.0}),
        (OpName.DENOISE, {"strength": 1.5}),
    ],
)
def test_validator_rejects_out_of_bounds(op_name: OpName, params: dict) -> None:
    op = Op(op_name=op_name, params=params, step_id="s1")
    with pytest.raises(ValueError, match="out of bounds"):
        validate_op(op)


def test_validator_rejects_disallowed_op() -> None:
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 1.0}, step_id="s1")
    with pytest.raises(ValueError, match="not in allowed set"):
        validate_op(op, allowed_ops={OpName.CROP})


def test_validator_rejects_bbox_on_size_changing_op() -> None:
    op = Op(
        op_name=OpName.CROP,
        params={"left": 0, "top": 0, "right": 32, "bottom": 32},
        bbox=BoundingBox(x=0, y=0, width=32, height=32),
        step_id="s1",
    )
    with pytest.raises(ValueError):
        validate_op(op)


def test_validator_accepts_valid_op() -> None:
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 1.0}, step_id="s1")
    validate_op(op)  # must not raise


def test_validate_op_graph_raises_on_first_bad_op() -> None:
    graph = OpGraph(
        ops=[
            Op(op_name=OpName.EXPOSURE, params={"ev": 0.5}, step_id="good"),
            Op(op_name=OpName.EXPOSURE, params={"ev": 99.0}, step_id="bad"),
        ]
    )
    with pytest.raises(ValueError):
        validate_op_graph(graph)


# ---------------------------------------------------------------------------
# Executor — golden image
# ---------------------------------------------------------------------------


def test_exposure_brightens_image() -> None:
    container = _container(np.full((64, 64, 3), 64, dtype=np.uint8))
    result = Executor().apply(container, _graph(_op(OpName.EXPOSURE, {"ev": 1.0})))
    np.testing.assert_allclose(result.container.pixels, 128, atol=1)


def test_exposure_clips_at_max() -> None:
    container = _container(np.full((64, 64, 3), 200, dtype=np.uint8))
    result = Executor().apply(container, _graph(_op(OpName.EXPOSURE, {"ev": 2.0})))
    assert np.all(result.container.pixels == 255)


def test_crop_reduces_dimensions() -> None:
    container = _container()
    result = Executor().apply(
        container,
        _graph(_op(OpName.CROP, {"left": 0, "top": 0, "right": 32, "bottom": 16})),
    )
    assert result.container.pixels.shape == (16, 32, 3)


def test_white_balance_shifts_channels() -> None:
    pixels = np.full((32, 32, 3), 128, dtype=np.uint8)
    container = _container(pixels)
    # High temperature → cooler (more blue, less red)
    result = Executor().apply(
        container, _graph(_op(OpName.WHITE_BALANCE, {"temperature": 10000.0}))
    )
    assert int(result.container.pixels[0, 0, 2]) > int(result.container.pixels[0, 0, 0])


def test_executor_chains_ops() -> None:
    container = _container(np.full((64, 64, 3), 64, dtype=np.uint8))
    graph = _graph(
        _op(OpName.EXPOSURE, {"ev": 1.0}),  # 64 → 128
        _op(OpName.CROP, {"left": 0, "top": 0, "right": 32, "bottom": 32}),
    )
    result = Executor().apply(container, graph)
    assert result.container.pixels.shape == (32, 32, 3)
    np.testing.assert_allclose(result.container.pixels, 128, atol=1)


def test_executor_respects_allowed_ops_policy() -> None:
    container = _container()
    graph = _graph(_op(OpName.EXPOSURE, {"ev": 1.0}))
    with pytest.raises(ValueError, match="not in allowed set"):
        Executor(allowed_ops={OpName.CROP}).apply(container, graph)


# ---------------------------------------------------------------------------
# Executor — bbox region isolation
# ---------------------------------------------------------------------------


def test_bbox_confines_exposure() -> None:
    pixels = np.full((64, 64, 3), 50, dtype=np.uint8)
    container = _container(pixels)

    bbox = BoundingBox(x=10, y=10, width=20, height=20)
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 2.0}, bbox=bbox, step_id="s1")
    result = Executor().apply(container, _graph(op))

    # Outside bbox: unchanged
    assert np.all(result.container.pixels[0, 0] == 50)
    assert np.all(result.container.pixels[63, 63] == 50)

    # Inside bbox: 50 * 4 = 200
    np.testing.assert_allclose(result.container.pixels[20, 20], 200, atol=1)


def test_bbox_edge_pixels_unchanged() -> None:
    pixels = np.full((64, 64, 3), 100, dtype=np.uint8)
    container = _container(pixels)
    bbox = BoundingBox(x=0, y=0, width=32, height=32)
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 2.0}, bbox=bbox, step_id="s1")
    result = Executor().apply(container, _graph(op))

    # Row/col 32 is just outside the bbox
    assert np.all(result.container.pixels[32, 32] == 100)
    assert np.all(result.container.pixels[0, 0] == 255)  # 100 * 4 clipped to 255


# ---------------------------------------------------------------------------
# Mask
# ---------------------------------------------------------------------------


def test_mask_true_inside_bbox() -> None:
    container = _container()
    bbox = BoundingBox(x=5, y=5, width=10, height=10)
    mask = bbox_to_mask(container, bbox)
    assert mask.shape == (64, 64)
    assert mask[5, 5] and mask[14, 14]
    assert not mask[4, 4] and not mask[15, 15]


def test_mask_clips_to_image_bounds() -> None:
    container = _container(np.zeros((10, 10, 3), dtype=np.uint8))
    bbox = BoundingBox(x=5, y=5, width=20, height=20)  # extends beyond image
    mask = bbox_to_mask(container, bbox)
    assert mask.shape == (10, 10)
    assert mask[9, 9]  # clamped: row 9, col 9 inside clipped region
    assert not mask[0, 0]  # outside


# ---------------------------------------------------------------------------
# Validator — inpaint backend / prompt rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,backend",
    [
        (OpName.BACKGROUND_REPLACE, Backend.OPENCV),
        (OpName.REGION_EDIT, Backend.OPENCV),
        (OpName.BACKGROUND_REPLACE, Backend.PHOTOSHOP),
        (OpName.REGION_EDIT, Backend.PHOTOSHOP),
    ],
)
def test_validator_inpaint_no_prompt_required_for_non_genai(op_name, backend) -> None:
    op = Op(op_name=op_name, params={}, backend=backend, step_id="s1")
    validate_op(op)  # must not raise


@pytest.mark.parametrize(
    "op_name",
    [OpName.BACKGROUND_REPLACE, OpName.REGION_EDIT],
)
def test_validator_inpaint_genai_requires_prompt(op_name) -> None:
    op = Op(op_name=op_name, params={}, backend=Backend.GENAI, step_id="s1")
    with pytest.raises(ValueError, match="missing required param"):
        validate_op(op)


# ---------------------------------------------------------------------------
# CV inpaint — pixel isolation invariant
# ---------------------------------------------------------------------------


def _container_with_spot(spot_value: int = 0) -> tuple[ImageContainer, BoundingBox]:
    """White 64x64 image with a black 10x10 spot at (20,20)."""
    pixels = np.full((64, 64, 3), 255, dtype=np.uint8)
    pixels[20:30, 20:30] = spot_value
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)
    bbox = BoundingBox(x=20, y=20, width=10, height=10)
    return container, bbox


def test_cv_inpaint_outside_bbox_unchanged() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    container, bbox = _container_with_spot(spot_value=0)
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    result = apply_inpaint(container, op)

    outside_mask = ~bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(result.pixels[outside_mask], container.pixels[outside_mask])


def test_cv_inpaint_modifies_inside_bbox() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    container, bbox = _container_with_spot(spot_value=0)
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    result = apply_inpaint(container, op)

    inside_mask = bbox_to_mask(container, bbox)
    # Black spot should be inpainted toward the white surroundings
    assert result.pixels[inside_mask].mean() > 128


def test_cv_inpaint_raises_without_bbox() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    container = _container()
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=None,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    with pytest.raises(ValueError, match="requires a bbox"):
        apply_inpaint(container, op)


def test_cv_inpaint_via_executor_end_to_end() -> None:
    container, bbox = _container_with_spot(spot_value=0)
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    result = Executor().apply(container, _graph(op))

    outside_mask = ~bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(
        result.container.pixels[outside_mask], container.pixels[outside_mask]
    )
