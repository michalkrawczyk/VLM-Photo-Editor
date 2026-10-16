"""Deterministic eval tier: the oracle plan for each synthetic case must pass its metric.

Guards the ops (Finding C) and the ImageReport numbers (Finding A) together, with no VLM.
Run just this tier verbosely: ``pytest -m eval tests/eval -s``.
"""

from __future__ import annotations

import pytest

from .cases import CASES
from .harness import run_oracle


@pytest.mark.eval
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_oracle_plan_passes_case_metric(case) -> None:
    result = run_oracle(case)
    print(f"\n[eval] {result}")
    assert result.passed, f"{case.name}: {case.why}\n{result}"


def _plan(ev: float):
    from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

    step = HumanStep(
        step_id="0b5d1e0a-6f43-4a77-9d0b-3a1f2c4e8a11",
        index=1,
        title="Open up shadows",
        why="Brightens the frame",
        op_names=["exposure"],
        op_params=[{"ev": ev}],
    )
    return HumanPlan(steps=[step])


@pytest.mark.eval
@pytest.mark.parametrize(
    "ev,expect_pass,expect_error",
    [(1.0, True, False), (-1.0, False, False), (99.0, False, True)],
    ids=["good_plan", "wrong_direction", "out_of_bounds_plan"],
)
def test_run_case_scores_planner_output(ev, expect_pass, expect_error) -> None:
    from .harness import run_case

    case = next(c for c in CASES if c.name == "underexposed")
    result = run_case(case, lambda container, intent: _plan(ev))
    assert result.passed is expect_pass
    assert (result.error is not None) is expect_error
    if not expect_error:
        assert result.n_steps == 1


@pytest.mark.eval
@pytest.mark.parametrize(
    "max_repairs,expect_pass,expect_repairs",
    [(0, False, 0), (2, True, 1)],
    ids=["no_repair_budget", "repaired_once"],
)
def test_run_case_repairs_rejected_plan(max_repairs, expect_pass, expect_repairs) -> None:
    """A plan the compiler rejects is revised (visible, bounded) and then scored."""
    from .harness import run_case

    case = next(c for c in CASES if c.name == "underexposed")
    result = run_case(
        case,
        lambda container, intent: _plan(99.0),
        lambda container, plan, error: _plan(1.0),
        max_repairs,
    )
    assert result.passed is expect_pass
    assert result.repairs == expect_repairs
    assert (result.error is None) is expect_pass


def _masked_plan():
    """mask + exposure compiles, but the executor needs a subject bbox the eval cannot supply."""
    from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

    step = HumanStep(
        step_id="1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
        index=1,
        title="Brighten the background",
        why="Lifts everything but the subject",
        op_names=["mask", "exposure"],
        op_params=[{}, {"ev": 1.0}],
    )
    return HumanPlan(steps=[step])


@pytest.mark.eval
@pytest.mark.parametrize(
    "max_repairs,expect_pass,expect_repairs",
    [(0, False, 0), (1, True, 1)],
    ids=["no_repair_budget", "execute_error_repaired"],
)
def test_run_case_repairs_execute_time_rejection(max_repairs, expect_pass, expect_repairs) -> None:
    """A masked edit with no resolvable subject fails at execute; it shares the repair budget."""
    from .harness import run_case

    case = next(c for c in CASES if c.name == "underexposed")
    result = run_case(
        case,
        lambda container, intent: _masked_plan(),
        lambda container, plan, error: _plan(1.0),
        max_repairs,
    )
    assert result.passed is expect_pass
    assert result.repairs == expect_repairs
    assert expect_pass or "bbox" in (result.error or "")
    if expect_pass:
        assert result.ops == ['exposure {"ev": 1.0}']


@pytest.mark.eval
def test_compare_reports_flips_and_deltas(tmp_path) -> None:
    from .compare import _load, compare
    from .harness import CaseResult, write_results

    base, new = tmp_path / "a.json", tmp_path / "b.json"
    write_results(
        [CaseResult("x", False, n_steps=3), CaseResult("y", True, n_steps=1)], base, label="a"
    )
    write_results(
        [CaseResult("x", True, n_steps=1, repairs=1), CaseResult("y", True, n_steps=1)],
        new,
        label="b",
    )
    out = compare(_load(str(base)), _load(str(new)))
    assert "pass-rate  0.50 -> 1.00" in out
    assert "x: FAIL -> pass" in out
    assert "y:" not in out  # unchanged cases are not flips
