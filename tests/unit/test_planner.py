from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.planner.compiler import Compiler, CompilerError
from vlm_photo_editor.schema.ops import OpName
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan, HumanStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(
    op_names: list[str],
    op_params: list[dict] | None = None,
    *,
    step_id: str | None = None,
    index: int = 1,
) -> HumanStep:
    return HumanStep(
        step_id=step_id or str(uuid.uuid4()),
        index=index,
        title="t",
        why="w",
        op_names=op_names,
        op_params=op_params or [],
    )


def _plan(*steps: HumanStep, mode: str = "full") -> HumanPlan:
    return HumanPlan(steps=list(steps), mode=mode)


# ---------------------------------------------------------------------------
# allowed_ops_for_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,expected,excluded",
    [
        ("full", OpName.EXPOSURE, None),
        ("background", OpName.BACKGROUND_REPLACE, OpName.CROP),
        ("frame", OpName.FRAME, OpName.EXPOSURE),
    ],
)
def test_allowed_ops_for_mode_membership(mode, expected, excluded):
    ops = allowed_ops_for_mode(mode)
    assert expected in ops
    if excluded is not None:
        assert excluded not in ops


def test_allowed_ops_for_mode_full_has_all():
    assert allowed_ops_for_mode("full") == set(OpName)


def test_allowed_ops_for_mode_unknown_raises():
    with pytest.raises(KeyError, match="Unknown edit mode"):
        allowed_ops_for_mode("bogus")


# ---------------------------------------------------------------------------
# Compiler — happy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,params",
    [
        ("crop", {"left": 0, "top": 0, "right": 100, "bottom": 80}),
        ("exposure", {"ev": 1.0}),
        ("rotate", {"angle": 90.0}),
        ("white_balance", {"temperature": 5500.0}),
        ("denoise", {}),
        ("frame", {"mode": "rule_of_thirds"}),
    ],
)
def test_compiler_happy_path(op_name, params):
    step = _step([op_name], [params], step_id="s1")
    result = Compiler().compile(_plan(step), "full")
    assert isinstance(result, CompilerResult)
    assert len(result.op_graph.ops) == 1
    assert result.op_graph.ops[0].op_name.value == op_name
    assert result.op_graph.ops[0].step_id == "s1"
    assert result.op_graph.ops[0].params == params


# ---------------------------------------------------------------------------
# Compiler — step-ID linkage
# ---------------------------------------------------------------------------


def test_compiler_step_id_linkage():
    s1 = _step(["exposure", "rotate"], [{"ev": 0.5}, {"angle": 45.0}], step_id="step-001", index=1)
    s2 = _step(
        ["crop"], [{"left": 0, "top": 0, "right": 200, "bottom": 150}], step_id="step-002", index=2
    )
    result = Compiler().compile(_plan(s1, s2), "full")
    assert result.op_graph.ops[0].step_id == "step-001"
    assert result.op_graph.ops[1].step_id == "step-001"
    assert result.op_graph.ops[2].step_id == "step-002"


# ---------------------------------------------------------------------------
# Compiler — op_params padding
# ---------------------------------------------------------------------------


def test_compiler_pads_missing_params_validator_catches():
    # crop needs left/top/right/bottom; op_params omitted → padded with {} → validator rejects
    step = _step(["crop"], [])
    with pytest.raises(CompilerError, match="missing required param"):
        Compiler().compile(_plan(step), "full")


# ---------------------------------------------------------------------------
# Compiler — mode enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,mode,params",
    [
        ("exposure", "background", {"ev": 1.0}),
        ("background_replace", "frame", {"prompt": "forest"}),
        ("region_edit", "frame", {"prompt": "blur"}),
    ],
)
def test_compiler_rejects_op_not_in_mode(op_name, mode, params):
    step = _step([op_name], [params])
    with pytest.raises(CompilerError):
        Compiler().compile(_plan(step, mode=mode), mode)


# ---------------------------------------------------------------------------
# Compiler — error cases
# ---------------------------------------------------------------------------


def test_compiler_rejects_unknown_op_name():
    step = _step(["sharpen"], [{}])
    with pytest.raises(CompilerError, match="unknown op"):
        Compiler().compile(_plan(step), "full")


def test_compiler_unknown_mode_raises_key_error():
    step = _step(["exposure"], [{"ev": 1.0}])
    with pytest.raises(KeyError):
        Compiler().compile(_plan(step), "invalid_mode")


def test_compiler_result_preserves_plan():
    plan = _plan(_step(["denoise"], [{}]))
    result = Compiler().compile(plan, "full")
    assert result.plan is plan


# ---------------------------------------------------------------------------
# Compiler — params shallow copy (mutation safety)
# ---------------------------------------------------------------------------


def test_compiler_params_are_shallow_copied():
    original_params = {"ev": 1.0}
    step = _step(["exposure"], [original_params], step_id="s1")
    result = Compiler().compile(_plan(step), "full")
    result.op_graph.ops[0].params["ev"] = 999.0
    assert original_params["ev"] == 1.0  # step params not mutated


# ---------------------------------------------------------------------------
# Schema — HumanStep op_params round-trip
# ---------------------------------------------------------------------------


def test_human_step_op_params_round_trip():
    step = HumanStep(
        step_id="s1",
        index=1,
        title="t",
        why="w",
        op_names=["exposure"],
        op_params=[{"ev": 1.5}],
    )
    restored = HumanStep.model_validate(step.model_dump())
    assert restored.op_params == [{"ev": 1.5}]
    assert restored.op_names == ["exposure"]


def test_human_step_op_params_defaults_empty():
    step = HumanStep(step_id="s1", index=1, title="t", why="w", op_names=[])
    assert step.op_params == []


# ---------------------------------------------------------------------------
# Planner — mocked LLM
# ---------------------------------------------------------------------------


def _mock_plan() -> HumanPlan:
    return _plan(_step(["exposure"], [{"ev": 1.0}]), mode="full")


@pytest.mark.parametrize("method", ["plan", "revise"])
def test_planner_calls_llm_returns_human_plan(method):
    mock_plan = _mock_plan()

    with patch("vlm_photo_editor.agents.planner.build_client") as mock_build:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_plan
        mock_build.return_value = mock_llm

        from vlm_photo_editor.agents.planner import Planner

        container = MagicMock()
        container.pixels = np.zeros((64, 64, 3), dtype=np.uint8)

        planner = Planner()

        if method == "plan":
            result = planner.plan(container, intent="make it pop")
        else:
            result = planner.revise(container, previous_plan=mock_plan, feedback="brighter")

        assert isinstance(result, HumanPlan)
        assert result.mode == "full"
        mock_llm.with_structured_output.return_value.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# Integration — real LLM round-trip (skipped in CI unless API key present)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_planner_compile_round_trip_integration():
    """Requires ANTHROPIC_API_KEY. Verifies end-to-end plan → compile."""
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.full((64, 64, 3), 128, dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/test.jpg"),
    )
    plan = Planner().plan(container, intent="Brighten and crop", mode="full")
    assert len(plan.steps) >= 1

    result = Compiler().compile(plan, "full")
    assert len(result.op_graph.ops) >= 1
    step_ids = {s.step_id for s in plan.steps}
    for op in result.op_graph.ops:
        assert op.step_id in step_ids
