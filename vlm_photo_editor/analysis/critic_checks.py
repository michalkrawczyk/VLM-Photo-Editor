"""Critic stage 1: deterministic checks of an executed edit against what its ops should do.

The expectation is derived from the compiled ops (never from model-written prose, which a
model can game): net exposure sign -> median luma, white_balance direction -> R/B ratio,
tone highlights/shadows -> P95/P5, denoise -> noise sigma, a levelling rotate -> smaller
tilt. Callers compute the two ``ImageReport``s; this module only compares them, so it needs
no image I/O.

Deliberately conservative: only global ops are checked, and tone/colour checks are skipped
when the plan reshapes the frame (crop/frame/large rotate), because that changes the pixels
being measured. A check that cannot be made is omitted, never reported as passed.
"""

from __future__ import annotations

from vlm_photo_editor.schema.ops import Op, OpGraph, OpName
from vlm_photo_editor.schema.report import ImageReport, StepCheck

_NEUTRAL_K = 6500.0  # must match pil_backend._white_balance / image_report._NEUTRAL_K
_MIN_NET_EV = 0.3
_MIN_NET_WB_K = 300.0
_MIN_TONE = 20.0  # |slider| below this may move a percentile by less than _MIN_LUMA_DELTA
_MIN_LUMA_DELTA = 0.003
_MIN_RATIO_DELTA = 0.005
_MIN_TILT_DEG = 0.5
_MIN_TILT_CONFIDENCE = 0.5
_MAX_CHECKED_ROTATE_DEG = 5.0
_MIN_NOISE_TO_CHECK = 1.0  # below this there is nothing for denoise to remove
_NEW_CLIPPING_PTS = 5.0  # blown highlights gained beyond this = artifact, whatever the plan said


def _is_global(op: Op) -> bool:
    return op.bbox is None and not op.params.get("invert")


def _reshapes_frame(graph: OpGraph) -> bool:
    for op in graph.ops:
        if op.op_name in (OpName.CROP, OpName.FRAME):
            return True
        if op.op_name is OpName.ROTATE and abs(float(op.params.get("angle", 0))) > (
            _MAX_CHECKED_ROTATE_DEG
        ):
            return True
    return False


def _pick(ops: list[Op], key: str) -> str | None:
    """step_id of the op with the largest |param| — the one most responsible for the effect."""
    return max(ops, key=lambda o: abs(float(o.params.get(key, 0)))).step_id if ops else None


def check_edit(graph: OpGraph, before: ImageReport, after: ImageReport) -> list[StepCheck]:
    """Return every check that could be made; callers treat any ``ok=False`` as a failure."""
    checks: list[StepCheck] = []
    global_ops = [op for op in graph.ops if _is_global(op)]

    if not _reshapes_frame(graph):
        exposure = [op for op in global_ops if op.op_name is OpName.EXPOSURE]
        net_ev = sum(float(op.params["ev"]) for op in exposure)
        if abs(net_ev) >= _MIN_NET_EV:
            delta = after.luma_p50 - before.luma_p50
            up = net_ev > 0
            saturated = after.luma_p50 >= 0.98 if up else after.luma_p50 <= 0.02
            checks.append(
                StepCheck(
                    step_id=_pick(exposure, "ev"),
                    op_name="exposure",
                    metric="luma_p50",
                    expected="increase" if up else "decrease",
                    before=before.luma_p50,
                    after=after.luma_p50,
                    ok=saturated or (delta if up else -delta) >= _MIN_LUMA_DELTA,
                )
            )

        # tone: only the slider whose end of the range no other term moves is checked —
        # exposure, contrast and the black/white points would blur which one did what.
        tone = [op for op in global_ops if op.op_name is OpName.TONE]
        if tone and not exposure:

            def net(key: str) -> float:
                return sum(float(op.params.get(key, 0)) for op in tone)

            if not net("contrast"):
                hl, sh = net("highlights"), net("shadows")
                if hl <= -_MIN_TONE and not net("whites") and 0.5 <= before.luma_p95 < 0.999:
                    checks.append(
                        StepCheck(
                            step_id=_pick(tone, "highlights"),
                            op_name="tone",
                            metric="luma_p95",
                            expected="decrease",
                            before=before.luma_p95,
                            after=after.luma_p95,
                            ok=before.luma_p95 - after.luma_p95 >= _MIN_LUMA_DELTA,
                        )
                    )
                if sh >= _MIN_TONE and not net("blacks") and 0.03 <= before.luma_p5 <= 0.5:
                    checks.append(
                        StepCheck(
                            step_id=_pick(tone, "shadows"),
                            op_name="tone",
                            metric="luma_p5",
                            expected="increase",
                            before=before.luma_p5,
                            after=after.luma_p5,
                            ok=after.luma_p5 - before.luma_p5 >= _MIN_LUMA_DELTA,
                        )
                    )

        wb = [op for op in global_ops if op.op_name is OpName.WHITE_BALANCE]
        net_k = sum(float(op.params["temperature"]) - _NEUTRAL_K for op in wb)
        if abs(net_k) >= _MIN_NET_WB_K:
            delta = after.cast_rb_ratio - before.cast_rb_ratio
            warmer = net_k > 0  # Lightroom convention: higher K = warmer = more R/B
            checks.append(
                StepCheck(
                    step_id=wb[-1].step_id,
                    op_name="white_balance",
                    metric="cast_rb_ratio",
                    expected="increase" if warmer else "decrease",
                    before=before.cast_rb_ratio,
                    after=after.cast_rb_ratio,
                    ok=(delta if warmer else -delta) >= _MIN_RATIO_DELTA,
                )
            )

        denoise = [op for op in global_ops if op.op_name is OpName.DENOISE]
        if denoise and before.noise_sigma >= _MIN_NOISE_TO_CHECK:
            checks.append(
                StepCheck(
                    step_id=denoise[0].step_id,
                    op_name="denoise",
                    metric="noise_sigma",
                    expected="decrease",
                    before=before.noise_sigma,
                    after=after.noise_sigma,
                    ok=after.noise_sigma < before.noise_sigma,
                )
            )

    rotate = [op for op in global_ops if op.op_name is OpName.ROTATE]
    if (
        len(rotate) == 1
        and _MIN_TILT_DEG <= abs(float(rotate[0].params["angle"])) <= _MAX_CHECKED_ROTATE_DEG
        and before.tilt_deg is not None
        and abs(before.tilt_deg) >= _MIN_TILT_DEG
        and (before.tilt_confidence or 0.0) >= _MIN_TILT_CONFIDENCE
    ):
        after_tilt = abs(after.tilt_deg) if after.tilt_deg is not None else 0.0
        checks.append(
            StepCheck(
                step_id=rotate[0].step_id,
                op_name="rotate",
                metric="tilt_deg",
                expected="decrease",
                before=abs(before.tilt_deg),
                after=after_tilt,
                ok=after_tilt < abs(before.tilt_deg),
            )
        )

    gained = after.clipped_highlight_pct - before.clipped_highlight_pct
    if gained > _NEW_CLIPPING_PTS:
        checks.append(
            StepCheck(
                step_id=_pick([op for op in global_ops if op.op_name is OpName.EXPOSURE], "ev"),
                op_name="any",
                metric="clipped_highlight_pct",
                expected="not_increase",
                before=before.clipped_highlight_pct,
                after=after.clipped_highlight_pct,
                ok=False,
            )
        )
    return checks
