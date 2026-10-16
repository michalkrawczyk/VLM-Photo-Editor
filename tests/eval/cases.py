"""Synthetic, tagged eval cases. No licensed photos: every image is generated from a seed.

Each case carries an *oracle*: the ops a competent editor would apply given the measured
``ImageReport``. The deterministic tier checks the oracle improves the metric the case is
about; the VLM tier (``harness.run_case``) checks a real planner reaches the same bar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Backend, Op, OpName
from vlm_photo_editor.schema.report import ImageReport

from . import metrics

_SRC = Path("/eval/synthetic.png")


def _scene(seed: int = 0, size: tuple[int, int] = (240, 320)) -> np.ndarray:
    """Float 0-1 RGB test scene: sky-to-ground gradient, a few blocks, light grain."""
    rng = np.random.default_rng(seed)
    h, w = size
    y = np.linspace(0.75, 0.35, h, dtype=np.float32)[:, None, None]
    img = np.repeat(np.repeat(y, w, axis=1), 3, axis=2) * np.array([0.9, 1.0, 1.1], np.float32)
    for _ in range(6):
        x0, y0 = int(rng.integers(0, w - 60)), int(rng.integers(0, h - 50))
        img[y0 : y0 + 40, x0 : x0 + 50] = rng.uniform(0.15, 0.85, 3).astype(np.float32)
    return np.clip(img + rng.normal(0, 0.004, img.shape).astype(np.float32), 0, 1)


def _to_container(rgb01: np.ndarray, bit_depth: int = 8) -> ImageContainer:
    if bit_depth == 16:
        pixels = np.rint(np.clip(rgb01, 0, 1) * 65535).astype(np.uint16)
    else:
        pixels = np.rint(np.clip(rgb01, 0, 1) * 255).astype(np.uint8)
    return ImageContainer(pixels=pixels, bit_depth=bit_depth, source_path=_SRC)


def _op(name: OpName, params: dict) -> Op:
    return Op(op_name=name, params=params, backend=Backend.PIL, step_id="oracle")


@dataclass(frozen=True)
class EvalCase:
    name: str
    tags: tuple[str, ...]
    intent: str
    make_image: Callable[[], ImageContainer]
    oracle: Callable[[ImageReport], list[Op]]
    passes: Callable[[ImageReport, ImageReport], bool]
    why: str = field(default="", compare=False)  # human reading of the pass criterion


def _tilted() -> ImageContainer:
    img = np.full((300, 400, 3), 0.16, dtype=np.float32)
    rise = 400 * np.tan(np.radians(3.0))
    for y in (90, 150, 210):
        cv2.line(img, (0, y), (399, round(y - rise)), (0.9, 0.9, 0.9), 3)
    return _to_container(img)


def _bright_sky() -> ImageContainer:
    img = _scene(6) * 0.6
    img[:90] = np.linspace(0.97, 0.88, 90, dtype=np.float32)[:, None, None]  # bright, not blown
    return _to_container(img)


def _noisy() -> ImageContainer:
    rng = np.random.default_rng(7)
    base = np.full((256, 256, 3), 0.5, dtype=np.float32)
    return _to_container(base + rng.normal(0, 0.05, base.shape).astype(np.float32))


def _clipped() -> ImageContainer:
    img = _scene(3) * 0.6
    img[:80, :120] = 1.0  # blown sky corner
    return _to_container(img)


def _neutral() -> ImageContainer:
    """Gray-world balanced scene: nothing for white_balance (or anything else) to fix."""
    img = _scene(5)
    return _to_container(np.clip(img * (img.mean() / img.mean(axis=(0, 1))) * 0.8, 0, 1))


def _flat_colour() -> ImageContainer:
    img = _scene(8)
    grey = img.mean(axis=-1, keepdims=True)
    return _to_container(grey + 0.25 * (img - grey))  # colours present but washed out


def _soft() -> ImageContainer:
    return _to_container(cv2.GaussianBlur(_scene(9), (0, 0), 2.0))


CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "underexposed",
        ("underexposed", "landscape"),
        "this is too dark, brighten it",
        lambda: _to_container(_scene(1) * 0.35),
        lambda r: [_op(OpName.EXPOSURE, {"ev": 1.0})],
        metrics.brighter_without_new_clipping,
        "median luma up, highlight clipping not worse by >1 pt",
    ),
    EvalCase(
        "underexposed_16bit",
        ("underexposed", "16bit"),
        "this is too dark, brighten it",
        lambda: _to_container(_scene(1) * 0.35, bit_depth=16),
        lambda r: [_op(OpName.EXPOSURE, {"ev": 1.0})],
        metrics.brighter_without_new_clipping,
        "same as underexposed, and dtype/bit_depth must survive the edit",
    ),
    EvalCase(
        "warm_cast",
        ("warm_cast", "portrait"),
        "fix the orange colour cast",
        lambda: _to_container(_scene(2) * np.array([1.0, 0.9, 0.7], np.float32)),
        lambda r: [_op(OpName.WHITE_BALANCE, {"temperature": r.suggested_wb_temperature})],
        metrics.cast_reduced,
        "|log(R/B)| smaller than before",
    ),
    EvalCase(
        "cool_cast",
        ("cool_cast", "product"),
        "this looks too blue, neutralise it",
        lambda: _to_container(_scene(4) * np.array([0.7, 0.9, 1.0], np.float32)),
        lambda r: [_op(OpName.WHITE_BALANCE, {"temperature": r.suggested_wb_temperature})],
        metrics.cast_reduced,
        "|log(R/B)| smaller than before",
    ),
    EvalCase(
        "tilted_horizon",
        ("tilted_horizon", "landscape"),
        "straighten the horizon",
        _tilted,
        lambda r: [_op(OpName.ROTATE, {"angle": -(r.tilt_deg or 0.0)})],
        metrics.level_within_one_degree,
        "residual tilt < 1 degree",
    ),
    EvalCase(
        "clipped_highlights",
        ("clipped_highlights", "landscape"),
        "recover the blown highlights",
        _clipped,
        lambda r: [_op(OpName.EXPOSURE, {"ev": -0.7})],
        metrics.highlight_clipping_reduced,
        "clipped_highlight_pct strictly lower",
    ),
    EvalCase(
        "bright_sky",
        ("bright_sky", "landscape"),
        "the sky is too bright, bring it down without darkening the rest",
        _bright_sky,
        lambda r: [_op(OpName.TONE, {"highlights": -60})],
        metrics.highlights_down_midtones_kept,
        "P95 down by >= 0.01 while median luma moves < 0.02",
    ),
    EvalCase(
        "noisy",
        ("high_iso", "product"),
        "clean up the noise",
        _noisy,
        lambda r: [_op(OpName.DENOISE, {})],
        metrics.noise_reduced,
        "noise_sigma at least 30 % lower",
    ),
    EvalCase(
        "flat_colour",
        ("flat_colour", "landscape"),
        "the colours look washed out, make them vivid",
        _flat_colour,
        lambda r: [_op(OpName.SATURATION, {"vibrance": 50})],
        metrics.saturation_raised,
        "saturation_mean up >= 30 %, highlight clipping not worse by >1 pt",
    ),
    EvalCase(
        "soft",
        ("soft", "product"),
        "this looks soft, sharpen it",
        _soft,
        lambda r: [_op(OpName.SHARPEN, {"amount": 150, "radius": 2.0})],
        metrics.sharpness_raised,
        "Laplacian-variance sharpness up >= 30 % without raising noise",
    ),
    EvalCase(
        "already_fine",
        ("well_exposed", "landscape"),
        "make it better",
        _neutral,
        lambda r: [],
        metrics.left_essentially_unchanged,
        "median luma, colour cast and clipping all stay put (prefer no edit to a gratuitous one)",
    ),
)
