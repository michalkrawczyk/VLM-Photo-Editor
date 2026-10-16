"""Deterministic pass criteria: functions of (before, after) ``ImageReport``."""

from __future__ import annotations

import math

from vlm_photo_editor.schema.report import ImageReport


def brighter_without_new_clipping(before: ImageReport, after: ImageReport) -> bool:
    return (
        after.luma_p50 > before.luma_p50
        and after.clipped_highlight_pct <= before.clipped_highlight_pct + 1.0
    )


def cast_reduced(before: ImageReport, after: ImageReport) -> bool:
    return abs(math.log(after.cast_rb_ratio)) < abs(math.log(before.cast_rb_ratio))


def level_within_one_degree(before: ImageReport, after: ImageReport) -> bool:
    return after.tilt_deg is None or abs(after.tilt_deg) < 1.0


def highlight_clipping_reduced(before: ImageReport, after: ImageReport) -> bool:
    return after.clipped_highlight_pct < before.clipped_highlight_pct


def highlights_down_midtones_kept(before: ImageReport, after: ImageReport) -> bool:
    """Bright end pulled down while the median barely moves — what exposure cannot do."""
    return after.luma_p95 <= before.luma_p95 - 0.01 and abs(after.luma_p50 - before.luma_p50) < 0.02


def noise_reduced(before: ImageReport, after: ImageReport) -> bool:
    return after.noise_sigma <= 0.7 * before.noise_sigma


def saturation_raised(before: ImageReport, after: ImageReport) -> bool:
    return (
        after.saturation_mean >= 1.3 * before.saturation_mean
        and after.clipped_highlight_pct <= before.clipped_highlight_pct + 1.0
    )


def sharpness_raised(before: ImageReport, after: ImageReport) -> bool:
    return after.sharpness >= 1.3 * before.sharpness and after.noise_sigma <= 1.5 * (
        before.noise_sigma + 0.5
    )


def left_essentially_unchanged(before: ImageReport, after: ImageReport) -> bool:
    """For an already-fine image: 'make it better' must not drift tone, colour or clipping."""
    return (
        abs(after.luma_p50 - before.luma_p50) < 0.05
        and abs(math.log(after.cast_rb_ratio) - math.log(before.cast_rb_ratio)) < 0.1
        and after.clipped_highlight_pct <= before.clipped_highlight_pct + 1.0
        and after.clipped_shadow_pct <= before.clipped_shadow_pct + 1.0
    )
