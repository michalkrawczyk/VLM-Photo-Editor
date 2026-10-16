from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from vlm_photo_editor.analysis import compute_report
from vlm_photo_editor.analysis.exif import parse_exif
from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.ops.executor import Executor
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName

_SRC = Path("/fake/source.jpg")


def _container(pixels: np.ndarray, metadata: dict | None = None) -> ImageContainer:
    depth = 16 if pixels.dtype == np.uint16 else 8
    return ImageContainer(pixels=pixels, bit_depth=depth, source_path=_SRC, metadata=metadata or {})


def _flat(rgb: tuple[int, int, int], size: tuple[int, int] = (120, 160)) -> np.ndarray:
    return np.full((*size, 3), rgb, dtype=np.uint8)


def _apply(container: ImageContainer, name: OpName, params: dict) -> ImageContainer:
    op = Op(op_name=name, params=params, backend=Backend.PIL, step_id="s1")
    return Executor().apply(container, OpGraph(ops=[op])).container


def _lined(tilt_deg: float) -> np.ndarray:
    """Dark scene with a few long parallel horizontals, visually tilted CCW by tilt_deg."""
    img = np.full((300, 400, 3), 40, dtype=np.uint8)
    rise = 400 * np.tan(np.radians(tilt_deg))
    for y in (90, 150, 210):
        cv2.line(img, (0, y), (399, round(y - rise)), (230, 230, 230), 3)
    return img


# ---------------------------------------------------------------------------
# Tone / clipping / saturation
# ---------------------------------------------------------------------------


def test_flat_gray_report() -> None:
    r = compute_report(_container(_flat((128, 128, 128))))
    assert (r.width, r.height) == (160, 120)
    assert r.luma_mean == pytest.approx(128 / 255, abs=0.002)
    assert r.luma_p1 == r.luma_p99 == r.luma_p50
    assert r.clipped_shadow_pct == r.clipped_highlight_pct == 0.0
    assert r.cast_label == "neutral"
    assert r.suggested_wb_temperature == pytest.approx(6500, abs=1)
    assert r.saturation_mean == 0.0
    assert r.noise_sigma == 0.0
    assert (r.tilt_deg, r.tilt_confidence) == (None, None)


@pytest.mark.parametrize(
    "value,field",
    [(255, "clipped_highlight_pct"), (0, "clipped_shadow_pct")],
)
def test_clipping_percentages(value: int, field: str) -> None:
    pixels = _flat((128, 128, 128), (100, 100))
    pixels[:20, :25] = value  # 500 px of 10 000 = 5 %
    r = compute_report(_container(pixels))
    assert getattr(r, field) == pytest.approx(5.0, abs=0.1)


def test_uint16_matches_uint8() -> None:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, (90, 120, 3), dtype=np.uint8)
    r8 = compute_report(_container(pixels))
    r16 = compute_report(_container(pixels.astype(np.uint16) * 257))
    assert r16.luma_mean == pytest.approx(r8.luma_mean, abs=0.002)
    assert r16.clipped_highlight_pct == pytest.approx(r8.clipped_highlight_pct, abs=0.1)
    assert r16.cast_rb_ratio == pytest.approx(r8.cast_rb_ratio, abs=0.01)


def test_alpha_and_gray_inputs_are_accepted() -> None:
    rgba = np.dstack([_flat((100, 100, 100)), np.zeros((120, 160), np.uint8)])
    gray = np.full((50, 60), 100, dtype=np.uint8)
    assert compute_report(_container(rgba)).luma_mean == pytest.approx(100 / 255, abs=0.002)
    assert compute_report(_container(gray)).luma_mean == pytest.approx(100 / 255, abs=0.002)


# ---------------------------------------------------------------------------
# Colour cast + the suggested white-balance value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rgb,label,direction",
    [
        ((140, 128, 100), "warm", "below"),  # tungsten-ish cast -> cool it -> T below 6500
        ((80, 128, 190), "cool", "above"),  # blue cast -> warm it -> T above 6500
    ],
)
def test_cast_label_and_suggested_wb_removes_cast(rgb, label, direction) -> None:
    container = _container(_flat(rgb))
    r = compute_report(container)
    assert r.cast_label == label
    assert (r.suggested_wb_temperature < 6500) is (direction == "below")

    # Round trip through the real backend: applying the suggestion equalises R and B.
    fixed = _apply(container, OpName.WHITE_BALANCE, {"temperature": r.suggested_wb_temperature})
    after = compute_report(fixed)
    assert after.cast_label == "neutral"
    assert after.cast_rb_ratio == pytest.approx(1.0, abs=0.03)


def test_extreme_cast_clamps_suggestion_to_op_bounds() -> None:
    # R/B ~6 in linear light needs a multiplier the op can't express (T >= 1000 K).
    r = compute_report(_container(_flat((190, 128, 80))))
    assert r.cast_label == "warm"
    assert r.suggested_wb_temperature == 1000.0


# ---------------------------------------------------------------------------
# Sharpness / noise
# ---------------------------------------------------------------------------


def test_sharpness_and_noise_estimates() -> None:
    rng = np.random.default_rng(1)
    checker = (np.indices((128, 128)).sum(axis=0) % 2 * 255).astype(np.uint8)
    sharp = np.dstack([checker] * 3)
    soft = cv2.GaussianBlur(sharp, (0, 0), 3)
    assert compute_report(_container(sharp)).sharpness > compute_report(_container(soft)).sharpness

    noisy = np.clip(128 + rng.normal(0, 5, (256, 256, 3)), 0, 255).astype(np.uint8)
    sigma = compute_report(_container(noisy)).noise_sigma
    # independent per-channel sigma 5 -> luma sigma 5 * sqrt(0.2126^2 + 0.7152^2 + 0.0722^2) = 3.75
    assert sigma == pytest.approx(3.75, abs=0.5)
    assert compute_report(_container(_flat((128, 128, 128)))).noise_sigma == 0.0


# ---------------------------------------------------------------------------
# Tilt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tilt", [3.0, -2.0, 0.0])
def test_tilt_measured_and_levelled_by_rotate(tilt: float) -> None:
    container = _container(_lined(tilt))
    r = compute_report(container)
    assert r.tilt_deg == pytest.approx(tilt, abs=0.6)
    assert r.tilt_confidence is not None and r.tilt_confidence > 0.5

    levelled = compute_report(_apply(container, OpName.ROTATE, {"angle": -r.tilt_deg}))
    assert levelled.tilt_deg is None or abs(levelled.tilt_deg) < 0.6


def test_tilt_low_confidence_without_structure() -> None:
    rng = np.random.default_rng(2)
    texture = rng.integers(0, 256, (300, 400, 3), dtype=np.uint8)
    r = compute_report(_container(texture))
    assert r.tilt_deg is None or (r.tilt_confidence or 0) < 0.5


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------


def test_exif_round_trip_through_loader(tmp_path: Path) -> None:
    exif = Image.Exif()
    ifd = exif.get_ifd(0x8769)
    ifd[0x8827] = 400  # ISO
    ifd[0x829A] = 1 / 125  # exposure time
    ifd[0x829D] = 2.8  # f-number
    ifd[0x920A] = 35.0  # focal length
    ifd[0xA403] = 1  # manual WB
    ifd[0x9204] = -0.5  # exposure bias
    exif[0x010F] = "SecretMaker"  # not whitelisted
    path = tmp_path / "shot.jpg"
    Image.fromarray(_flat((100, 100, 100)), "RGB").save(path, exif=exif)

    summary = compute_report(load(path)).exif
    assert summary.iso == 400
    assert summary.exposure_time_s == pytest.approx(1 / 125, rel=0.02)
    assert summary.f_number == pytest.approx(2.8, abs=0.05)
    assert summary.focal_length_mm == pytest.approx(35.0)
    assert summary.wb_mode == "manual"
    assert summary.exposure_bias_ev == pytest.approx(-0.5, abs=0.05)
    assert "SecretMaker" not in summary.model_dump_json()


@pytest.mark.parametrize("raw", [None, b"", b"not exif at all", "str", 12, b"Exif\x00\x00garbage"])
def test_unreadable_exif_yields_empty_summary(raw) -> None:
    summary = parse_exif(raw)
    assert summary.model_dump() == {
        "iso": None,
        "exposure_time_s": None,
        "f_number": None,
        "focal_length_mm": None,
        "wb_mode": None,
        "exposure_bias_ev": None,
    }


# ---------------------------------------------------------------------------
# Critic stage 1 (analysis.critic_checks)
# ---------------------------------------------------------------------------


def _scene_pixels() -> np.ndarray:
    rng = np.random.default_rng(3)
    base = np.linspace(70, 150, 160, dtype=np.float32)[None, :, None] * np.ones((120, 1, 3))
    return np.clip(base + rng.normal(0, 3, base.shape), 0, 255).astype(np.uint8)


def _noisy_pixels() -> np.ndarray:
    rng = np.random.default_rng(7)
    return np.clip(128 + rng.normal(0, 14, (200, 200, 3)), 0, 255).astype(np.uint8)


def _checks(pixels: np.ndarray, applied: tuple[OpName, dict], claimed: tuple[OpName, dict]):
    """Run `claimed` ops through check_edit, measured against the result of `applied`."""
    from vlm_photo_editor.analysis.critic_checks import check_edit

    before = _container(pixels)
    after = _apply(before, *applied)
    graph = OpGraph(
        ops=[Op(op_name=claimed[0], params=claimed[1], backend=Backend.PIL, step_id="s1")]
    )
    return check_edit(graph, compute_report(before), compute_report(after))


@pytest.mark.parametrize(
    "pixels,claimed,applied,expect_ok",
    [
        (_scene_pixels(), (OpName.EXPOSURE, {"ev": 1.0}), (OpName.EXPOSURE, {"ev": 1.0}), True),
        (_scene_pixels(), (OpName.EXPOSURE, {"ev": 1.0}), (OpName.EXPOSURE, {"ev": -1.0}), False),
        (
            _scene_pixels(),
            (OpName.WHITE_BALANCE, {"temperature": 4000}),
            (OpName.WHITE_BALANCE, {"temperature": 4000}),
            True,
        ),
        (
            _scene_pixels(),
            (OpName.WHITE_BALANCE, {"temperature": 4000}),
            (OpName.WHITE_BALANCE, {"temperature": 9000}),
            False,
        ),
        (_noisy_pixels(), (OpName.DENOISE, {}), (OpName.DENOISE, {}), True),
        (_noisy_pixels(), (OpName.DENOISE, {}), (OpName.EXPOSURE, {"ev": 0.0}), False),
        (_lined(3.0), (OpName.ROTATE, {"angle": -3.0}), (OpName.ROTATE, {"angle": -3.0}), True),
        (_lined(3.0), (OpName.ROTATE, {"angle": -3.0}), (OpName.ROTATE, {"angle": 3.0}), False),
        (
            _scene_pixels(),
            (OpName.TONE, {"highlights": -60}),
            (OpName.TONE, {"highlights": -60}),
            True,
        ),
        (
            _scene_pixels(),
            (OpName.TONE, {"highlights": -60}),
            (OpName.TONE, {"highlights": 60}),
            False,
        ),
        (_scene_pixels(), (OpName.TONE, {"shadows": 60}), (OpName.TONE, {"shadows": 60}), True),
        (_scene_pixels(), (OpName.TONE, {"shadows": 60}), (OpName.TONE, {"shadows": -60}), False),
    ],
    ids=[
        "exposure_up_ok",
        "exposure_up_but_darkened",
        "wb_cooler_ok",
        "wb_cooler_but_warmed",
        "denoise_ok",
        "denoise_but_unchanged",
        "level_ok",
        "level_but_worse",
        "tone_highlights_down_ok",
        "tone_highlights_down_but_brightened",
        "tone_shadows_up_ok",
        "tone_shadows_up_but_deepened",
    ],
)
def test_check_edit_matches_what_the_op_should_do(pixels, claimed, applied, expect_ok) -> None:
    checks = _checks(pixels, applied, claimed)
    assert len(checks) == 1, checks
    assert checks[0].ok is expect_ok
    assert checks[0].step_id == "s1"
    assert checks[0].describe()


def test_check_edit_skips_what_it_cannot_measure_and_flags_new_clipping() -> None:
    from vlm_photo_editor.analysis.critic_checks import check_edit
    from vlm_photo_editor.schema.ops import BoundingBox

    before = compute_report(_container(_scene_pixels()))
    ev = {"ev": 1.0}
    crop = Op(
        op_name=OpName.CROP,
        params={"left": 0, "top": 0, "right": 100, "bottom": 80},
        backend=Backend.PIL,
        step_id="c",
    )
    exposure = Op(op_name=OpName.EXPOSURE, params=ev, backend=Backend.PIL, step_id="e")
    local = exposure.model_copy(
        update={"bbox": BoundingBox(x=0, y=0, width=10, height=10), "step_id": "l"}
    )
    # Tone checks are skipped once the frame changes, and local ops are never judged globally.
    assert check_edit(OpGraph(ops=[crop, exposure]), before, before) == []
    assert check_edit(OpGraph(ops=[local]), before, before) == []

    blown = before.model_copy(update={"clipped_highlight_pct": before.clipped_highlight_pct + 12})
    flagged = [c for c in check_edit(OpGraph(ops=[exposure]), before, blown) if not c.ok]
    assert [(c.metric, c.step_id) for c in flagged] == [
        ("luma_p50", "e"),
        ("clipped_highlight_pct", "e"),
    ]
