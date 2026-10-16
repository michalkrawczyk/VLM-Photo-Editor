"""Bounded compile-and-repair loop shared by the single-image app flow and batch planning.

A plan that fails to compile (bad params, crop out of bounds, mask without a follower) is
handed back to the planner together with the error text, at most ``max_repairs`` times.
Every revision is recorded as a ``RepairNote`` so callers can show it: plans are never
rewritten silently (principle 3), and in manual mode the user still approves the result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vlm_photo_editor.planner.compiler import Compiler, CompilerError
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import OpGraph, OpName
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan


@dataclass(frozen=True)
class RepairNote:
    attempt: int  # 1-based index of the revision this error triggered
    error: str


class PlanRepairError(CompilerError):
    """Compile failed for good: not repairable, or the repair budget is spent.

    Carries the latest plan so the UI can still show what the planner last proposed.
    """

    def __init__(self, message: str, *, plan: HumanPlan, notes: list[RepairNote]) -> None:
        super().__init__(message, repairable=False)
        self.plan = plan
        self.notes = notes


# Sanity caps for freshly planned ops, far outside any realistic correction (the prompt asks
# for ev within ±1.5 and rotate within ±5). Deliberately not in PARAM_BOUNDS: those also
# validate saved recipes on replay, and tightening them would reject old recipes.
_MAX_NET_EV = 4.0
_MAX_OFF_AXIS_ROTATE_DEG = 20.0  # distance from the nearest multiple of 90 (orientation fixes)


def check_plan_sanity(op_graph: OpGraph) -> None:
    """Raise a repairable ``CompilerError`` for a valid-but-absurd plan (e.g. +6 EV).

    Matters most in the auto accept modes, where no human reads the numbers before execution.
    """
    exposure = [op for op in op_graph.ops if op.op_name is OpName.EXPOSURE]
    for op in exposure:
        if abs(float(op.params["ev"])) > _MAX_NET_EV:
            raise CompilerError(
                f"Step {op.step_id!r}: exposure ev {op.params['ev']} exceeds the sanity limit "
                f"of ±{_MAX_NET_EV:g}; use a smaller correction."
            )
    net_ev = sum(float(op.params["ev"]) for op in exposure if op.bbox is None)
    if abs(net_ev) > _MAX_NET_EV:
        raise CompilerError(
            f"Exposure steps add up to {net_ev:+g} EV, beyond the sanity limit of "
            f"±{_MAX_NET_EV:g}; use fewer or smaller exposure steps."
        )
    for op in op_graph.ops:
        if op.op_name is OpName.ROTATE:
            angle = float(op.params["angle"])
            off_axis = abs(angle - 90.0 * round(angle / 90.0))
            if off_axis > _MAX_OFF_AXIS_ROTATE_DEG:
                raise CompilerError(
                    f"Step {op.step_id!r}: rotate angle {angle:g} is {off_axis:g} degrees off "
                    f"a right angle (sanity limit {_MAX_OFF_AXIS_ROTATE_DEG:g}); straightening "
                    "needs only a few degrees."
                )


def compile_checked(
    plan: HumanPlan,
    mode: str,
    detected_subject: DetectedSubject | None,
    width: int,
    height: int,
    compiler: Compiler | None = None,
) -> CompilerResult:
    """Compile ``plan``, then check its crops fit this image and its numbers are sane.

    Raises ``ValueError`` (``CompilerError`` for the sanity check) on failure.
    """
    from vlm_photo_editor.ops.validator import validate_crop_bounds

    result = (compiler or Compiler()).compile(plan, mode, detected_subject=detected_subject)
    validate_crop_bounds(result.op_graph, width, height)
    check_plan_sanity(result.op_graph)
    return result


def plans_equivalent(a: HumanPlan, b: HumanPlan) -> bool:
    """True when two plans do the same thing; ignores ids and prose (titles, reasons)."""

    def _shape(plan: HumanPlan) -> tuple:
        steps = [(s.op_names, s.op_params) for s in plan.steps]
        return steps, plan.outpaint_needed, plan.chosen_framing_mode

    return _shape(a) == _shape(b)


def compile_with_repair(
    plan: HumanPlan,
    compile_fn: Callable[[HumanPlan], CompilerResult],
    revise_fn: Callable[[HumanPlan, str], HumanPlan],
    max_repairs: int,
) -> tuple[CompilerResult, list[RepairNote]]:
    """Compile ``plan``; on a repairable ``ValueError`` ask ``revise_fn`` for a fixed plan.

    ``compile_fn`` should also run any image-dependent checks (e.g. crop bounds) so they
    share the budget. ``revise_fn(plan, error_text)`` is a blocking planner call.
    """
    notes: list[RepairNote] = []
    for attempt in range(max_repairs + 1):
        try:
            return compile_fn(plan), notes
        except ValueError as exc:  # CompilerError, crop-bounds and pydantic errors all land here
            if not getattr(exc, "repairable", True) or attempt >= max_repairs:
                raise PlanRepairError(str(exc), plan=plan, notes=notes) from exc
            notes.append(RepairNote(attempt=attempt + 1, error=str(exc)))
            plan = revise_fn(plan, str(exc))
    raise AssertionError("unreachable")  # loop always returns or raises
