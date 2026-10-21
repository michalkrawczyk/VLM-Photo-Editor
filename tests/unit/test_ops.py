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


def _expected_ev(code: int, ev: float, max_val: int = 255) -> int:
    """Independent oracle: sRGB code value after ``ev`` stops in linear light (below the knee)."""
    v = code / max_val
    lin = v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    lin *= 2.0**ev
    enc = lin * 12.92 if lin <= 0.0031308 else 1.055 * lin ** (1 / 2.4) - 0.055
    return round(enc * max_val)


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
    op = Op(op_name=op_name, params=params, backend=Backend.PIL, step_id="s1")
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
        (OpName.TONE, {"shadows": 101.0}),
        (OpName.TONE, {"contrast": -150.0}),
        (OpName.SATURATION, {"saturation": 101.0}),
        (OpName.SATURATION, {"vibrance": -150.0}),
        (OpName.SHARPEN, {"amount": 301.0}),
        (OpName.SHARPEN, {"threshold": -1.0}),
        (OpName.SHARPEN, {"radius": 0.1}),
    ],
)
def test_validator_rejects_out_of_bounds(op_name: OpName, params: dict) -> None:
    op = Op(op_name=op_name, params=params, backend=Backend.PIL, step_id="s1")
    with pytest.raises(ValueError, match="out of bounds"):
        validate_op(op)


def test_validator_rejects_disallowed_op() -> None:
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 1.0}, backend=Backend.PIL, step_id="s1")
    with pytest.raises(ValueError, match="not in allowed set"):
        validate_op(op, allowed_ops={OpName.CROP})


def test_validator_rejects_bbox_on_size_changing_op() -> None:
    op = Op(
        op_name=OpName.CROP,
        params={"left": 0, "top": 0, "right": 32, "bottom": 32},
        bbox=BoundingBox(x=0, y=0, width=32, height=32),
        backend=Backend.PIL,
        step_id="s1",
    )
    with pytest.raises(ValueError):
        validate_op(op)


def test_validator_accepts_valid_op() -> None:
    op = Op(op_name=OpName.EXPOSURE, params={"ev": 1.0}, backend=Backend.PIL, step_id="s1")
    validate_op(op)  # must not raise


# ---------------------------------------------------------------------------
# S-C1 — closed param contract: reject keys the catalog does not declare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,params",
    [
        (OpName.EXPOSURE, {"ev": 1.0, "angl": 5}),  # typo for a param that doesn't exist
        (OpName.ROTATE, {"angle": 10.0, "expand": True}),
        (OpName.CROP, {"left": 0, "top": 0, "right": 8, "bottom": 8, "pad": 1}),
    ],
)
def test_validator_rejects_unknown_param(op_name: OpName, params: dict) -> None:
    op = Op(op_name=op_name, params=params, backend=Backend.PIL, step_id="s1")
    with pytest.raises(ValueError, match="unknown param"):
        validate_op(op)


def test_validator_accepts_declared_optional_params() -> None:
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={"prompt": "a field", "model": "m", "n": 2, "seed": 7},
        bbox=BoundingBox(x=1, y=1, width=8, height=8),
        backend=Backend.GENAI,
        step_id="s1",
    )
    validate_op(op)  # must not raise


def test_validator_accepts_compiler_injected_params() -> None:
    op = Op(
        op_name=OpName.EXPOSURE,
        params={"ev": 1.0, "invert": True, "focus_x": 0, "focus_y": 0, "focus_w": 4, "focus_h": 4},
        backend=Backend.PIL,
        step_id="s1",
    )
    validate_op(op)  # must not raise


def test_validate_op_graph_raises_on_first_bad_op() -> None:
    graph = OpGraph(
        ops=[
            Op(op_name=OpName.EXPOSURE, params={"ev": 0.5}, backend=Backend.PIL, step_id="good"),
            Op(op_name=OpName.EXPOSURE, params={"ev": 99.0}, backend=Backend.PIL, step_id="bad"),
        ]
    )
    with pytest.raises(ValueError):
        validate_op_graph(graph)


# ---------------------------------------------------------------------------
# Executor — golden image
# ---------------------------------------------------------------------------


def test_exposure_is_linear_light() -> None:
    # +1 EV doubles linear light, not the gamma-encoded code: 64 -> ~90, not 128.
    container = _container(np.full((64, 64, 3), 64, dtype=np.uint8))
    result = Executor().apply(container, _graph(_op(OpName.EXPOSURE, {"ev": 1.0})))
    np.testing.assert_allclose(result.container.pixels, _expected_ev(64, 1.0), atol=1)
    assert _expected_ev(64, 1.0) == 90


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
def test_exposure_highlight_shoulder_has_no_hard_clip(dtype, maxv) -> None:
    ramp = np.linspace(0, maxv, 256, dtype=np.float64).astype(dtype)
    container = _container(
        np.tile(ramp[:, None, None], (1, 8, 3)), bit_depth=16 if dtype == np.uint16 else 8
    )
    out = Executor().apply(container, _graph(_op(OpName.EXPOSURE, {"ev": 0.5}))).container.pixels
    column = out[:, 0, 0].astype(np.int64)
    assert out.dtype == dtype
    assert (np.diff(column) >= 0).all()  # monotonic
    assert column[-1] == maxv  # white stays white
    assert column[0] == 0  # black stays black
    # A gamma-space multiply by 2**0.5 hard-clips every code above ~180 (70 % of full scale) to
    # white; the shoulder must keep those highlights distinct.
    assert column[200] < maxv
    assert len(np.unique(column[200:])) > 20


def test_exposure_preserves_alpha_and_hue() -> None:
    pixels = np.zeros((8, 8, 4), dtype=np.uint8)
    pixels[..., :3] = (200, 100, 50)
    pixels[..., 3] = 77
    out = Executor().apply(_container(pixels), _graph(_op(OpName.EXPOSURE, {"ev": 0.5})))
    assert (out.container.pixels[..., 3] == 77).all()
    r, g, b = (int(c) for c in out.container.pixels[0, 0, :3])
    assert r > g > b  # channel order (hue) preserved


def _tone_ramp(dtype, maxv: int, params: dict) -> np.ndarray:
    ramp = np.linspace(0, maxv, 256, dtype=np.float64).astype(dtype)
    container = _container(
        np.tile(ramp[:, None, None], (1, 4, 3)), bit_depth=16 if dtype == np.uint16 else 8
    )
    out = Executor().apply(container, _graph(_op(OpName.TONE, params))).container.pixels
    assert out.dtype == dtype
    return out[:, 0, 0].astype(np.int64)


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
@pytest.mark.parametrize(
    "params,region,direction",
    [
        ({"shadows": 50}, slice(20, 80), 1),
        ({"shadows": -50}, slice(20, 80), -1),
        ({"highlights": -50}, slice(180, 240), -1),
        ({"highlights": 50}, slice(180, 240), 1),
        ({"contrast": 50}, slice(160, 230), 1),
        ({"contrast": 50}, slice(25, 95), -1),
    ],
    ids=[
        "shadows_up",
        "shadows_down",
        "highlights_down",
        "highlights_up",
        "contrast_hi",
        "contrast_lo",
    ],
)
def test_tone_moves_its_range_and_keeps_endpoints(dtype, maxv, params, region, direction) -> None:
    before = np.linspace(0, maxv, 256, dtype=np.float64).astype(dtype).astype(np.int64)
    after = _tone_ramp(dtype, maxv, params)
    assert (np.diff(after) >= 0).all()  # monotonic
    assert (after[0], after[-1]) == (0, maxv)  # these sliders leave black and white alone
    assert (np.sign(after[region] - before[region]) == direction).all()


@pytest.mark.parametrize(
    "params,black,white",
    [({}, 0, 255), ({"blacks": 100}, 26, 255), ({"whites": -100}, 0, 230)],
    ids=["identity", "blacks_lift_black_point", "whites_grey_out_white"],
)
def test_tone_black_and_white_points(params, black, white) -> None:
    after = _tone_ramp(np.uint8, 255, params)
    assert (after[0], after[-1]) == (black, white)
    if not params:
        np.testing.assert_array_equal(after, np.linspace(0, 255, 256).astype(np.uint8))


def test_tone_preserves_alpha() -> None:
    pixels = np.zeros((8, 8, 4), dtype=np.uint8)
    pixels[..., :3] = 60
    pixels[..., 3] = 77
    out = Executor().apply(_container(pixels), _graph(_op(OpName.TONE, {"shadows": 80})))
    assert (out.container.pixels[..., 3] == 77).all()
    assert (out.container.pixels[..., :3] > 60).all()


def _chroma(pixels: np.ndarray) -> np.ndarray:
    rgb = pixels[..., :3].astype(np.float64)
    return rgb.max(axis=-1) - rgb.min(axis=-1)


def _colour_patches(dtype, maxv: int) -> np.ndarray:
    """Row 0: muted colour; row 1: vivid colour (same hue family)."""
    patches = np.array([[[0.55, 0.50, 0.45]], [[0.90, 0.30, 0.10]]]) * maxv
    return np.tile(patches, (1, 4, 1)).astype(dtype)


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
@pytest.mark.parametrize(
    "params,direction",
    [
        ({"saturation": 50}, 1),
        ({"saturation": -50}, -1),
        ({"vibrance": 50}, 1),
        ({"vibrance": -50}, -1),
    ],
)
def test_saturation_moves_chroma_and_keeps_dtype(dtype, maxv, params, direction) -> None:
    before = _colour_patches(dtype, maxv)
    out = (
        Executor()
        .apply(
            _container(before, bit_depth=16 if dtype == np.uint16 else 8),
            _graph(_op(OpName.SATURATION, params)),
        )
        .container.pixels
    )
    assert out.dtype == dtype
    assert (np.sign(_chroma(out) - _chroma(before)) == direction).all()


@pytest.mark.parametrize("params", [{}, {"saturation": 0, "vibrance": 0}])
def test_saturation_zero_is_identity(params) -> None:
    before = _colour_patches(np.uint8, 255)
    out = Executor().apply(_container(before), _graph(_op(OpName.SATURATION, params)))
    np.testing.assert_array_equal(out.container.pixels, before)


def test_saturation_minus_100_is_greyscale() -> None:
    out = (
        Executor()
        .apply(
            _container(_colour_patches(np.uint8, 255)),
            _graph(_op(OpName.SATURATION, {"saturation": -100})),
        )
        .container.pixels
    )
    assert (_chroma(out) <= 1).all()


def test_vibrance_moves_muted_colours_more_than_vivid() -> None:
    before = _colour_patches(np.uint8, 255)
    out = (
        Executor()
        .apply(_container(before), _graph(_op(OpName.SATURATION, {"vibrance": 60})))
        .container.pixels
    )
    gain = _chroma(out)[:, 0] / _chroma(before)[:, 0]
    assert gain[0] > gain[1]


def test_saturation_preserves_alpha() -> None:
    pixels = np.zeros((8, 8, 4), dtype=np.uint8)
    pixels[..., :3] = (200, 100, 50)
    pixels[..., 3] = 77
    out = Executor().apply(_container(pixels), _graph(_op(OpName.SATURATION, {"saturation": 40})))
    assert (out.container.pixels[..., 3] == 77).all()
    assert _chroma(out.container.pixels)[0, 0] > _chroma(pixels)[0, 0]


def _soft_edge(dtype, maxv: int) -> np.ndarray:
    """Vertical step edge blurred over a few columns, in colour."""
    ramp = np.clip((np.arange(32) - 13.5) / 5.0, 0.0, 1.0) * 0.4 + 0.3
    return np.tile((ramp * maxv)[None, :, None], (16, 1, 3)).astype(dtype)


def _edge_contrast(pixels: np.ndarray) -> float:
    row = pixels[8, :, 1].astype(np.float64)
    return float(row.max() - row.min())


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
def test_sharpen_steepens_edge_and_keeps_dtype(dtype, maxv) -> None:
    before = _soft_edge(dtype, maxv)
    out = (
        Executor()
        .apply(
            _container(before, bit_depth=16 if dtype == np.uint16 else 8),
            _graph(_op(OpName.SHARPEN, {"amount": 150, "radius": 1.5})),
        )
        .container.pixels
    )
    assert out.dtype == dtype
    assert _edge_contrast(out) > _edge_contrast(before)  # overshoot either side of the edge
    np.testing.assert_array_equal(out[:, :4], before[:, :4])  # flat areas untouched


@pytest.mark.parametrize("params", [{"amount": 0}, {"amount": 200, "threshold": 255}])
def test_sharpen_identity_cases(params) -> None:
    before = _soft_edge(np.uint8, 255)
    out = Executor().apply(_container(before), _graph(_op(OpName.SHARPEN, params)))
    np.testing.assert_array_equal(out.container.pixels, before)


def test_sharpen_preserves_alpha_and_hue() -> None:
    pixels = np.zeros((16, 32, 4), dtype=np.uint8)
    pixels[..., :3] = _soft_edge(np.uint8, 255) * np.array([1.0, 0.6, 0.3])[None, None, :]
    pixels[..., 3] = 77
    out = Executor().apply(_container(pixels), _graph(_op(OpName.SHARPEN, {"amount": 100})))
    assert (out.container.pixels[..., 3] == 77).all()
    r, g, b = (int(c) for c in out.container.pixels[8, 2, :3])
    assert r > g > b


def test_crop_reduces_dimensions() -> None:
    container = _container()
    result = Executor().apply(
        container,
        _graph(_op(OpName.CROP, {"left": 0, "top": 0, "right": 32, "bottom": 16})),
    )
    assert result.container.pixels.shape == (16, 32, 3)


@pytest.mark.parametrize(
    "temperature,red_vs_blue",
    [(4000.0, "cooler"), (6500.0, "neutral"), (10000.0, "warmer")],
)
def test_white_balance_follows_lightroom_convention(temperature, red_vs_blue) -> None:
    # Lightroom: HIGHER temperature = WARMER (red up, blue down); neutral at 6500 K.
    container = _container(np.full((32, 32, 3), 128, dtype=np.uint8))
    out = (
        Executor()
        .apply(container, _graph(_op(OpName.WHITE_BALANCE, {"temperature": temperature})))
        .container.pixels
    )
    r, g, b = (int(out[0, 0, c]) for c in range(3))
    assert g == 128  # green is the reference channel
    if red_vs_blue == "warmer":
        assert r > 128 > b
    elif red_vs_blue == "cooler":
        assert b > 128 > r
    else:
        assert (r, b) == (128, 128)


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
def test_white_balance_neutral_is_identity_and_keeps_alpha(dtype, maxv) -> None:
    ramp = np.linspace(0, maxv, 64).astype(dtype)
    pixels = np.stack([ramp, ramp[::-1], ramp, np.full_like(ramp, 9)], axis=-1)[None]
    container = _container(pixels, bit_depth=16 if dtype == np.uint16 else 8)
    neutral = Executor().apply(
        container, _graph(_op(OpName.WHITE_BALANCE, {"temperature": 6500.0}))
    )
    np.testing.assert_array_equal(neutral.container.pixels, pixels)
    warm = Executor().apply(container, _graph(_op(OpName.WHITE_BALANCE, {"temperature": 9000.0})))
    np.testing.assert_array_equal(warm.container.pixels[..., 3], pixels[..., 3])


def test_executor_chains_ops() -> None:
    container = _container(np.full((64, 64, 3), 64, dtype=np.uint8))
    graph = _graph(
        _op(OpName.EXPOSURE, {"ev": 1.0}),  # 64 → 90 (linear light)
        _op(OpName.CROP, {"left": 0, "top": 0, "right": 32, "bottom": 32}),
    )
    result = Executor().apply(container, graph)
    assert result.container.pixels.shape == (32, 32, 3)
    np.testing.assert_allclose(result.container.pixels, _expected_ev(64, 1.0), atol=1)


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
    op = Op(
        op_name=OpName.EXPOSURE, params={"ev": 2.0}, bbox=bbox, backend=Backend.PIL, step_id="s1"
    )
    result = Executor().apply(container, _graph(op))

    # Outside bbox: unchanged
    assert np.all(result.container.pixels[0, 0] == 50)
    assert np.all(result.container.pixels[63, 63] == 50)

    # Inside bbox: +2 EV in linear light
    np.testing.assert_allclose(result.container.pixels[20, 20], _expected_ev(50, 2.0), atol=1)


def test_bbox_edge_pixels_unchanged() -> None:
    pixels = np.full((64, 64, 3), 100, dtype=np.uint8)
    container = _container(pixels)
    bbox = BoundingBox(x=0, y=0, width=32, height=32)
    op = Op(
        op_name=OpName.EXPOSURE, params={"ev": 2.0}, bbox=bbox, backend=Backend.PIL, step_id="s1"
    )
    result = Executor().apply(container, _graph(op))

    # Row/col 32 is just outside the bbox
    assert np.all(result.container.pixels[32, 32] == 100)
    np.testing.assert_allclose(result.container.pixels[0, 0], _expected_ev(100, 2.0), atol=1)


# ---------------------------------------------------------------------------
# Executor — region coords remapped when CROP/FRAME ran earlier in the graph
# ---------------------------------------------------------------------------


def test_crop_then_bbox_remaps_to_cropped_space() -> None:
    pixels = np.full((64, 64, 3), 50, dtype=np.uint8)
    container = _container(pixels)
    graph = _graph(
        _op(OpName.CROP, {"left": 20, "top": 20, "right": 64, "bottom": 64}),
        # bbox expressed in the ORIGINAL 64x64 image's coordinates.
        _op(OpName.EXPOSURE, {"ev": 2.0}, bbox=BoundingBox(x=30, y=30, width=10, height=10)),
    )
    result = Executor().apply(container, graph)

    assert result.container.pixels.shape == (44, 44, 3)
    # Remapped bbox is [10,20)x[10,20) in the cropped image.
    np.testing.assert_allclose(result.container.pixels[15, 15], _expected_ev(50, 2.0), atol=1)
    assert np.all(result.container.pixels[0, 0] == 50)  # outside remapped bbox


def test_crop_then_bbox_outside_cropped_region_raises() -> None:
    container = _container(np.full((64, 64, 3), 50, dtype=np.uint8))
    graph = _graph(
        _op(OpName.CROP, {"left": 20, "top": 20, "right": 64, "bottom": 64}),
        # Original-space bbox entirely left/above the crop origin.
        _op(OpName.EXPOSURE, {"ev": 2.0}, bbox=BoundingBox(x=0, y=0, width=10, height=10)),
    )
    with pytest.raises(ValueError, match="falls outside"):
        Executor().apply(container, graph)


def test_crop_then_crop_uses_plan_start_coordinates() -> None:
    """OE-B1: a second CROP is expressed in the original image's coordinates (like bbox)."""
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(100)[None, :]  # red channel encodes the original column
    pixels[:, :, 1] = np.arange(100)[:, None]  # green channel encodes the original row
    graph = _graph(
        _op(OpName.CROP, {"left": 20, "top": 20, "right": 100, "bottom": 100}),
        _op(OpName.CROP, {"left": 30, "top": 40, "right": 90, "bottom": 90}),
    )

    out = Executor().apply(_container(pixels), graph).container.pixels

    assert out.shape == (50, 60, 3)
    assert tuple(out[0, 0, :2]) == (30, 40)  # top-left is original (x=30, y=40)
    assert tuple(out[-1, -1, :2]) == (89, 89)


def test_crop_then_crop_beyond_first_crop_clamps_to_current_image() -> None:
    """OE-B1 repro: crop(0,0,80,80) then crop(10,10,90,90) both pass plan-time bounds
    on 100x100; the second must clamp to what the first left, not crash."""
    graph = _graph(
        _op(OpName.CROP, {"left": 0, "top": 0, "right": 80, "bottom": 80}),
        _op(OpName.CROP, {"left": 10, "top": 10, "right": 90, "bottom": 90}),
    )

    out = Executor().apply(_container(np.zeros((100, 100, 3), dtype=np.uint8)), graph)

    assert out.container.pixels.shape == (70, 70, 3)


def test_crop_then_crop_outside_first_crop_raises() -> None:
    graph = _graph(
        _op(OpName.CROP, {"left": 50, "top": 50, "right": 100, "bottom": 100}),
        _op(OpName.CROP, {"left": 0, "top": 0, "right": 40, "bottom": 40}),
    )
    with pytest.raises(ValueError, match="Crop region falls outside"):
        Executor().apply(_container(np.zeros((100, 100, 3), dtype=np.uint8)), graph)


def test_frame_then_crop_uses_plan_start_coordinates() -> None:
    """OE-B1: FRAME shifts the origin too, so a following CROP is remapped through it."""
    pixels = np.zeros((100, 200, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.arange(200)[None, :]
    frame = _op(
        OpName.FRAME,
        {
            "mode": "negative_space",
            "focus_x": 150.0,
            "focus_y": 40.0,
            "focus_w": 4.0,
            "focus_h": 4.0,
        },
    )
    framed = Executor().apply(_container(pixels), _graph(frame)).container
    assert framed.width < 200  # FRAME actually moved the origin
    crop_left = 160
    out = (
        Executor()
        .apply(
            _container(pixels),
            _graph(
                frame, _op(OpName.CROP, {"left": crop_left, "top": 0, "right": 190, "bottom": 100})
            ),
        )
        .container.pixels
    )

    assert out.shape[1] == 30
    assert out[0, 0, 0] == crop_left


def test_crop_then_frame_remaps_focus() -> None:
    pixels = np.zeros((50, 200, 3), dtype=np.uint8)
    pixels[25, 105] = 255  # marker: kept only if focus_x is remapped into cropped space
    container = _container(pixels)
    graph = _graph(
        _op(OpName.CROP, {"left": 100, "top": 0, "right": 200, "bottom": 50}),
        _op(
            OpName.FRAME,
            {
                "mode": "negative_space",
                # focus_* expressed in the ORIGINAL 200-wide image's coordinates.
                "focus_x": 110.0,
                "focus_y": 20.0,
                "focus_w": 2.0,
                "focus_h": 2.0,
            },
        ),
    )
    result = Executor().apply(container, graph)

    assert result.container.pixels.shape == (50, 88, 3)
    assert result.container.pixels[25, 5, 0] == 255


def test_rotate_then_bbox_raises() -> None:
    container = _container()
    graph = _graph(
        _op(OpName.ROTATE, {"angle": 30.0}),
        _op(OpName.EXPOSURE, {"ev": 1.0}, bbox=BoundingBox(x=0, y=0, width=5, height=5)),
    )
    with pytest.raises(ValueError, match="ROTATE"):
        Executor().apply(container, graph)


# ---------------------------------------------------------------------------
# Tier 0 — rotate/denoise keep dtype + bit depth, bicubic resample, strength honoured
# ---------------------------------------------------------------------------

_DTYPE_ALPHA = [
    (np.uint8, 255, 3),
    (np.uint8, 255, 4),
    (np.uint16, 65535, 3),
    (np.uint16, 65535, 4),
]


def _flat(dtype, maxv: int, channels: int, size: int = 64, value: float = 0.5) -> ImageContainer:
    pixels = np.full((size, size, channels), int(maxv * value), dtype=dtype)
    return ImageContainer(
        pixels=pixels, bit_depth=16 if dtype == np.uint16 else 8, source_path=_FAKE_SRC
    )


@pytest.mark.parametrize("dtype,maxv,channels", _DTYPE_ALPHA)
@pytest.mark.parametrize("op_name,params", [(OpName.ROTATE, {"angle": 7.0}), (OpName.DENOISE, {})])
def test_rotate_denoise_preserve_dtype_and_bit_depth(dtype, maxv, channels, op_name, params):
    container = _flat(dtype, maxv, channels)
    out = Executor().apply(container, _graph(_op(op_name, params))).container
    assert out.pixels.dtype == dtype
    assert out.bit_depth == container.bit_depth
    assert out.pixels.shape[2] == channels


@pytest.mark.parametrize("angle,expected", [(0.0, (64, 64)), (90.0, (64, 64)), (45.0, (91, 91))])
def test_rotate_expanded_canvas_size(angle, expected):
    out = Executor().apply(_flat(np.uint8, 255, 3), _graph(_op(OpName.ROTATE, {"angle": angle})))
    assert out.container.pixels.shape[:2] == expected


def test_rotate_is_bicubic_not_nearest():
    # Hard black/white edge rotated off-axis: NEAREST yields only {0, 255}; a real
    # resampler produces intermediate grays along the edge.
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[:, 32:] = 255
    out = Executor().apply(_container(pixels), _graph(_op(OpName.ROTATE, {"angle": 10.0})))
    assert len(np.unique(out.container.pixels)) > 2


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
def test_rotate_crop_to_inscribed_removes_empty_corners(dtype, maxv):
    container = _flat(dtype, maxv, 3, size=128, value=1.0)
    plain = Executor().apply(container, _graph(_op(OpName.ROTATE, {"angle": 12.0}))).container
    cropped = (
        Executor()
        .apply(container, _graph(_op(OpName.ROTATE, {"angle": 12.0, "crop_to_inscribed": True})))
        .container
    )
    assert (plain.pixels == 0).any()  # default keeps the black wedges
    assert cropped.pixels.shape[0] < plain.pixels.shape[0]
    assert (cropped.pixels >= maxv - 1).all()  # inscribed rect is wholly source content


@pytest.mark.parametrize("dtype,maxv", [(np.uint8, 255), (np.uint16, 65535)])
def test_denoise_strength_blends_toward_median(dtype, maxv):
    pixels = np.zeros((9, 9, 3), dtype=dtype)
    pixels[4, 4] = maxv  # single hot pixel; 3x3 median removes it
    container = ImageContainer(
        pixels=pixels, bit_depth=8 if dtype == np.uint8 else 16, source_path=_FAKE_SRC
    )

    def run(params):
        return Executor().apply(container, _graph(_op(OpName.DENOISE, params))).container.pixels

    np.testing.assert_array_equal(run({"strength": 0.0}), pixels)  # identity
    np.testing.assert_array_equal(run({}), run({"strength": 1.0}))  # absent == full median
    assert run({}).max() == 0
    assert 0 < int(run({"strength": 0.5})[4, 4, 0]) < maxv


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


def test_fill_mask_without_bbox_raises_via_executor() -> None:
    """OE-P1: fill_mask with no bbox must not silently flatten the whole image."""
    op = _op(OpName.FILL_MASK, {"fill": 10})
    container = _container(np.full((64, 64, 3), 200, dtype=np.uint8))
    with pytest.raises(ValueError, match="requires a bbox"):
        Executor().apply(container, _graph(op))


def test_fill_mask_fills_inside_bbox_only() -> None:
    op = _op(OpName.FILL_MASK, {"fill": 10}, bbox=BoundingBox(x=5, y=5, width=10, height=10))
    container = _container(np.full((64, 64, 3), 200, dtype=np.uint8))
    result = Executor().apply(container, _graph(op))

    inside = bbox_to_mask(container, op.bbox)
    assert np.all(result.container.pixels[inside] == 10)
    assert np.all(result.container.pixels[~inside] == 200)


def test_fill_mask_invert_fills_outside_bbox() -> None:
    op = _op(
        OpName.FILL_MASK,
        {"fill": 10, "invert": True},
        bbox=BoundingBox(x=5, y=5, width=10, height=10),
    )
    container = _container(np.full((64, 64, 3), 200, dtype=np.uint8))
    result = Executor().apply(container, _graph(op))

    inside = bbox_to_mask(container, op.bbox)
    assert np.all(result.container.pixels[inside] == 200)
    assert np.all(result.container.pixels[~inside] == 10)


def test_pil_backend_raw_mask_op_raises() -> None:
    """A bare MASK op should never reach a backend post-compile (Compiler folds it into
    the next op); if one does anyway, fail loud rather than silently fill the image."""
    from vlm_photo_editor.ops.backends.pil_backend import apply as pil_apply

    op = _op(OpName.MASK, {})
    with pytest.raises(ValueError, match="does not support op"):
        pil_apply(_container(), op)


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


def test_cv_inpaint_handles_rgba() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    pixels = np.full((64, 64, 4), 255, dtype=np.uint8)
    pixels[20:30, 20:30, :3] = 0
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)
    bbox = BoundingBox(x=20, y=20, width=10, height=10)
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )

    result = apply_inpaint(container, op)

    assert result.pixels.shape[2] == 4
    np.testing.assert_array_equal(result.pixels[..., 3], pixels[..., 3])
    outside_mask = ~bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(result.pixels[outside_mask], container.pixels[outside_mask])


def test_cv_denoise_handles_rgba() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply

    pixels = np.full((64, 64, 4), 128, dtype=np.uint8)
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)
    op = Op(op_name=OpName.DENOISE, params={}, bbox=None, backend=Backend.OPENCV, step_id="s1")

    result = apply(container, op)

    assert result.pixels.shape[2] == 4
    np.testing.assert_array_equal(result.pixels[..., 3], pixels[..., 3])


# ---------------------------------------------------------------------------
# OPS-B2 — 16-bit cv_backend: * 257 reconstruction (no low-byte zeroing) + warning
# ---------------------------------------------------------------------------


def test_cv_inpaint_16bit_reconstructs_full_range(caplog) -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    pixels = np.full((64, 64, 3), 65535, dtype=np.uint16)
    pixels[20:30, 20:30] = 0
    container = ImageContainer(pixels=pixels, bit_depth=16, source_path=_FAKE_SRC)
    bbox = BoundingBox(x=20, y=20, width=10, height=10)
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    with caplog.at_level("WARNING"):
        result = apply_inpaint(container, op)

    assert result.pixels.dtype == np.uint16
    inside = bbox_to_mask(container, bbox)
    # << 8 would cap the inpainted region at 255*256=65280; * 257 reaches 65535.
    assert result.pixels[inside].max() == 65535
    assert "uint8-only" in caplog.text


def test_cv_denoise_16bit_reconstructs_full_range(caplog) -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply

    pixels = np.full((64, 64, 3), 65535, dtype=np.uint16)
    container = ImageContainer(pixels=pixels, bit_depth=16, source_path=_FAKE_SRC)
    op = Op(op_name=OpName.DENOISE, params={}, bbox=None, backend=Backend.OPENCV, step_id="s1")

    with caplog.at_level("WARNING"):
        result = apply(container, op)

    assert result.pixels.dtype == np.uint16
    # * 257 keeps the low byte populated; << 8 would zero it (banding, OPS-B2).
    assert int(result.pixels.max()) & 0xFF != 0
    assert int(result.pixels.max()) > 254 * 256  # beyond what << 8 could produce
    assert "uint8-only" in caplog.text


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


# ---------------------------------------------------------------------------
# OPS-B3 — bbox_to_mask rejects negative origin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x,y",
    [(-1, 0), (0, -1), (-5, -3)],
)
def test_bbox_to_mask_rejects_negative_origin(x: int, y: int) -> None:
    container = _container()
    bbox = BoundingBox(x=max(x, 0), y=max(y, 0), width=10, height=10)
    # Directly construct a bbox-like object with negative coords to bypass Pydantic
    from vlm_photo_editor.schema.ops import BoundingBox as BB

    class _BadBox(BB):
        model_config = {"arbitrary_types_allowed": True}

        @classmethod
        def _bad(cls, x: int, y: int) -> "BB":
            obj = cls.__new__(cls)
            object.__setattr__(obj, "x", x)
            object.__setattr__(obj, "y", y)
            object.__setattr__(obj, "width", 10)
            object.__setattr__(obj, "height", 10)
            return obj

    bad_bbox = _BadBox._bad(x, y)
    with pytest.raises(ValueError, match="non-negative"):
        bbox_to_mask(container, bad_bbox)


# ---------------------------------------------------------------------------
# OPS-B4 — genai_backend raises ValueError (not KeyError) for missing prompt
# ---------------------------------------------------------------------------


def test_genai_backend_raises_valueerror_for_missing_prompt() -> None:
    from vlm_photo_editor.ops.backends.genai_backend import apply

    container = _container()
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={},  # no prompt
        backend=Backend.GENAI,
        step_id="s1",
    )
    with pytest.raises(ValueError, match="requires 'prompt'"):
        apply(container, op)


# ---------------------------------------------------------------------------
# OPS-D2 — inpaint_radius bounds; method validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "radius",
    [0, 101, -1],
)
def test_validator_rejects_inpaint_radius_out_of_bounds(radius: int) -> None:
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={"inpaint_radius": radius},
        backend=Backend.OPENCV,
        step_id="s1",
    )
    with pytest.raises(ValueError, match="out of bounds"):
        validate_op(op)


def test_cv_inpaint_rejects_invalid_method() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_inpaint

    container, bbox = _container_with_spot()
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={"method": "biharmonic"},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    with pytest.raises(ValueError, match="'telea' or 'ns'"):
        apply_inpaint(container, op)


# ---------------------------------------------------------------------------
# SC-B1 — enum-param validation (frame.mode, region_edit.method)
# ---------------------------------------------------------------------------


_REGION_BBOX = BoundingBox(x=1, y=1, width=8, height=8)


@pytest.mark.parametrize(
    "op",
    [
        _op(OpName.FRAME, {"mode": "bogus"}),
        _op(OpName.FRAME, {"mode": "rule_of_third"}),  # near-miss typo
        _op(
            OpName.REGION_EDIT, {"method": "biharmonic"}, bbox=_REGION_BBOX, backend=Backend.OPENCV
        ),
    ],
)
def test_validator_rejects_unknown_enum_param(op) -> None:
    with pytest.raises(ValueError, match="not one of"):
        validate_op(op)


@pytest.mark.parametrize(
    "op",
    [
        _op(OpName.FRAME, {"mode": "rule_of_thirds"}),
        _op(OpName.FRAME, {"mode": "golden_ratio"}),
        _op(OpName.REGION_EDIT, {"method": "ns"}, bbox=_REGION_BBOX, backend=Backend.OPENCV),
        _op(OpName.REGION_EDIT, {"method": "blur"}, bbox=_REGION_BBOX, backend=Backend.OPENCV),
    ],
)
def test_validator_accepts_known_enum_param(op) -> None:
    validate_op(op)  # must not raise


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


# ---------------------------------------------------------------------------
# CV blur (region_edit, method="blur")
# ---------------------------------------------------------------------------


def _container_with_checkerboard() -> tuple[ImageContainer, BoundingBox]:
    """64x64 mid-gray image with a high-contrast checkerboard in a 20x20 bbox at (20,20)."""
    pixels = np.full((64, 64, 3), 128, dtype=np.uint8)
    row, col = np.indices((20, 20))
    checker = ((row + col) % 2 * 255).astype(np.uint8)
    pixels[20:40, 20:40, :] = checker[..., None]
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)
    bbox = BoundingBox(x=20, y=20, width=20, height=20)
    return container, bbox


def test_apply_blur_smooths_inside_bbox_leaves_outside_unchanged() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_blur

    container, bbox = _container_with_checkerboard()
    op = _op(OpName.REGION_EDIT, {"method": "blur", "radius": 5}, bbox=bbox, backend=Backend.OPENCV)
    result = apply_blur(container, op)

    outside_mask = ~bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(result.pixels[outside_mask], container.pixels[outside_mask])

    inside_mask = bbox_to_mask(container, bbox)
    assert result.pixels[inside_mask].std() < container.pixels[inside_mask].std()


def test_apply_blur_invert_targets_outside_bbox() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_blur

    container, bbox = _container_with_checkerboard()
    op = _op(
        OpName.REGION_EDIT,
        {"method": "blur", "radius": 5, "invert": True},
        bbox=bbox,
        backend=Backend.OPENCV,
    )
    result = apply_blur(container, op)

    inside_mask = bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(result.pixels[inside_mask], container.pixels[inside_mask])


def test_apply_blur_raises_without_bbox() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_blur

    op = _op(OpName.REGION_EDIT, {"method": "blur"}, backend=Backend.OPENCV)
    with pytest.raises(ValueError, match="requires a bbox"):
        apply_blur(_container(), op)


def test_apply_blur_preserves_alpha_channel() -> None:
    from vlm_photo_editor.ops.backends.cv_backend import apply_blur

    pixels = np.full((64, 64, 4), 128, dtype=np.uint8)
    pixels[20:40, 20:40, 3] = 77
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)
    bbox = BoundingBox(x=20, y=20, width=20, height=20)
    op = _op(OpName.REGION_EDIT, {"method": "blur", "radius": 5}, bbox=bbox, backend=Backend.OPENCV)

    result = apply_blur(container, op)

    np.testing.assert_array_equal(result.pixels[..., 3], pixels[..., 3])


def test_region_edit_blur_via_executor_end_to_end() -> None:
    container, bbox = _container_with_checkerboard()
    op = Op(
        op_name=OpName.REGION_EDIT,
        params={"method": "blur", "radius": 5},
        bbox=bbox,
        backend=Backend.OPENCV,
        step_id="s1",
    )
    result = Executor().apply(container, _graph(op))

    outside_mask = ~bbox_to_mask(container, bbox)
    np.testing.assert_array_equal(
        result.container.pixels[outside_mask], container.pixels[outside_mask]
    )


# ---------------------------------------------------------------------------
# OE-B3 — bbox starting outside the image is rejected, not a silent no-op
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("x,y", [(64, 0), (0, 64), (100, 100), (64, 64)])
def test_bbox_to_mask_rejects_origin_outside_image(x: int, y: int) -> None:
    container = _container()  # 64x64
    bbox = BoundingBox(x=x, y=y, width=10, height=10)
    with pytest.raises(ValueError, match="outside"):
        bbox_to_mask(container, bbox)


def test_bbox_to_mask_far_edge_still_clamps() -> None:
    container = _container()  # 64x64
    bbox = BoundingBox(x=60, y=60, width=20, height=20)
    mask = bbox_to_mask(container, bbox)
    assert mask.shape == (64, 64)
    assert mask[60:, 60:].all()
    assert mask.sum() == 16


# ---------------------------------------------------------------------------
# OE-B4 — non-numeric / bool CROP params raise ValueError (not TypeError)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["angl", None, True, [1]])
def test_validate_op_crop_rejects_non_numeric_params(bad: object) -> None:
    op = _op(OpName.CROP, {"left": bad, "top": 0, "right": 32, "bottom": 32})
    with pytest.raises(ValueError, match="must be a number"):
        validate_op(op)


def test_validate_op_crop_accepts_numeric_string() -> None:
    # A numeric string coerces cleanly instead of raising TypeError past the compiler.
    op = _op(OpName.CROP, {"left": "0", "top": "0", "right": "32", "bottom": "32"})
    validate_op(op)  # must not raise


def test_validate_op_crop_rejects_fractional_pixels() -> None:
    op = _op(OpName.CROP, {"left": 0, "top": 0, "right": 80.9, "bottom": 32})
    with pytest.raises(ValueError, match="whole number"):
        validate_op(op)


def test_validate_op_bounded_param_non_numeric_raises_valueerror() -> None:
    op = Op(op_name=OpName.EXPOSURE, params={"ev": "abc"}, backend=Backend.PIL, step_id="s1")
    with pytest.raises(ValueError, match="must be a number"):
        validate_op(op)
