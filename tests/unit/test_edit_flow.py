from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from langgraph.types import Command

from vlm_photo_editor.agents.edit_flow import build_edit_graph
from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import AcceptMode, Backend, Op, OpGraph, OpName, RiskTier
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(op_names, op_params=None):
    return HumanStep(
        step_id=str(uuid.uuid4()),
        index=1,
        title="t",
        why="w",
        op_names=op_names,
        op_params=op_params or [],
    )


def _plan(*steps, mode="full"):
    return HumanPlan(steps=list(steps), mode=mode)


def _low_risk_op_graph():
    return OpGraph(
        ops=[
            Op(
                op_name=OpName.DENOISE,
                params={},
                step_id="s1",
                risk_tier=RiskTier.LOW,
                backend=Backend.PIL,
            )
        ]
    )


def _high_risk_op_graph():
    return OpGraph(
        ops=[
            Op(
                op_name=OpName.BACKGROUND_REPLACE,
                params={"prompt": "forest"},
                step_id="s1",
                risk_tier=RiskTier.HIGH,
                backend=Backend.GENAI,
            )
        ]
    )


def _compile_result(op_graph):
    r = MagicMock()
    r.op_graph = op_graph
    return r


def _make_container():
    return ImageContainer(
        pixels=np.zeros((64, 64, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/test.jpg"),
    )


def _initial_state(accept_mode=AcceptMode.MANUAL, mode="full") -> dict:
    return {
        "container": _make_container(),
        "intent": "make it pop",
        "mode": mode,
        "accept_mode": accept_mode,
        "prefs": None,
        "plan": None,
        "op_graph": None,
        "feedback": None,
        "approved": False,
    }


# ---------------------------------------------------------------------------
# Manual mode — approve on first prompt
# ---------------------------------------------------------------------------


def test_manual_mode_approve_first_pass():
    plan = _plan(_step(["denoise"]))
    op_graph = _low_risk_op_graph()
    thread = {"configurable": {"thread_id": "t1"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        # First invoke: generate_plan → compile → await_human (interrupt)
        result = graph.invoke(_initial_state(AcceptMode.MANUAL), thread)

    assert result["plan"] is plan
    assert result["op_graph"] is op_graph

    # Resume: user approves
    with patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls2:
        mock_compiler_cls2.return_value.compile.return_value = _compile_result(op_graph)
        final = graph.invoke(Command(resume={"approved": True}), thread)

    assert final["approved"] is True


# ---------------------------------------------------------------------------
# Manual mode — request change then approve
# ---------------------------------------------------------------------------


def test_manual_mode_revise_then_approve():
    plan_v1 = _plan(_step(["denoise"]))
    plan_v2 = _plan(_step(["exposure"], [{"ev": 1.0}]))
    op_graph = _low_risk_op_graph()
    thread = {"configurable": {"thread_id": "t2"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan_v1
        mock_planner_cls.return_value.revise.return_value = plan_v2
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        # First invoke → interrupt at await_human
        graph.invoke(_initial_state(AcceptMode.MANUAL), thread)

        # Resume with feedback: routes to revise_plan → compile → await_human again
        graph.invoke(Command(resume={"approved": False, "feedback": "make it brighter"}), thread)
        mock_planner_cls.return_value.revise.assert_called_once()

    # Final approval
    with patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls2:
        mock_compiler_cls2.return_value.compile.return_value = _compile_result(op_graph)
        final = graph.invoke(Command(resume={"approved": True}), thread)

    assert final["approved"] is True


# ---------------------------------------------------------------------------
# Auto mode — low-risk skips human
# ---------------------------------------------------------------------------


def test_auto_mode_low_risk_skips_human():
    plan = _plan(_step(["denoise"]))
    op_graph = _low_risk_op_graph()
    thread = {"configurable": {"thread_id": "t3"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        # Should run to END without any interrupt
        final = graph.invoke(_initial_state(AcceptMode.AUTO), thread)

    assert final["op_graph"] is op_graph
    # never visited await_human → approved stays False
    assert final.get("approved") is False


# ---------------------------------------------------------------------------
# Auto mode — high-risk still requires approval
# ---------------------------------------------------------------------------


def test_auto_mode_high_risk_requires_human():
    plan = _plan(_step(["background_replace"], [{"prompt": "forest"}]))
    op_graph = _high_risk_op_graph()
    thread = {"configurable": {"thread_id": "t4"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        # Should interrupt at await_human (high-risk overrides auto)
        result = graph.invoke(_initial_state(AcceptMode.AUTO), thread)

    assert result["op_graph"] is op_graph  # compiled before interrupt
    assert graph.get_state(thread).next == ("await_human",)


# ---------------------------------------------------------------------------
# Full-auto mode — always skips human regardless of risk tier
# ---------------------------------------------------------------------------


def test_full_auto_mode_skips_human_regardless_of_risk():
    plan = _plan(_step(["background_replace"], [{"prompt": "forest"}]))
    op_graph = _high_risk_op_graph()
    thread = {"configurable": {"thread_id": "t5"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        # Should run to END without any interrupt, even for high-risk ops
        final = graph.invoke(_initial_state(AcceptMode.FULL_AUTO), thread)

    assert final["op_graph"] is op_graph
    assert graph.get_state(thread).next == ()  # at END


# ---------------------------------------------------------------------------
# State shape — plan and op_graph set after first invoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accept_mode,op_graph_fn",
    [
        (AcceptMode.MANUAL, _high_risk_op_graph),  # manual — always interrupts
        (AcceptMode.AUTO, _high_risk_op_graph),  # auto + high-risk — interrupts
    ],
)
def test_initial_invoke_sets_plan_and_op_graph(accept_mode, op_graph_fn):
    plan = _plan(_step(["denoise"]))
    op_graph = op_graph_fn()
    thread = {"configurable": {"thread_id": f"t-shape-{accept_mode.value}"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        result = graph.invoke(_initial_state(accept_mode), thread)

    assert result["plan"] is plan
    assert result["op_graph"] is op_graph
