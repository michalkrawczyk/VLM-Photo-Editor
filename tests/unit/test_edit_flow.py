from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from langgraph.types import Command

from vlm_photo_editor.agents.edit_flow import build_edit_graph
from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import (
    AcceptMode,
    Backend,
    FramingIntent,
    FramingMode,
    Op,
    OpGraph,
    OpName,
    RiskTier,
)
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
        op_params=op_params if op_params is not None else [{} for _ in op_names],
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


def _medium_risk_op_graph():
    return OpGraph(
        ops=[
            Op(
                op_name=OpName.FILL_MASK,
                params={},
                step_id="s1",
                risk_tier=RiskTier.MEDIUM,
                backend=Backend.PIL,
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
        "framing_intent": None,
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
    with (
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls2,
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_compiler_cls2.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )
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
    with (
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls2,
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_compiler_cls2.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )
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
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )

        # Should run to END without any interrupt
        final = graph.invoke(_initial_state(AcceptMode.AUTO_LOW), thread)

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
        result = graph.invoke(_initial_state(AcceptMode.AUTO_LOW), thread)

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
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )

        # Should run to END without any interrupt, even for high-risk ops
        final = graph.invoke(_initial_state(AcceptMode.FULL_AUTO), thread)

    assert final["op_graph"] is op_graph
    assert graph.get_state(thread).next == ()  # at END


# ---------------------------------------------------------------------------
# T3 — AUTO_MEDIUM mode coverage
# ---------------------------------------------------------------------------


def test_auto_medium_skips_human_for_medium_risk():
    plan = _plan(_step(["region_edit"], [{"prompt": "blur"}]))
    op_graph = _medium_risk_op_graph()
    thread = {"configurable": {"thread_id": "t_am1"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )

        final = graph.invoke(_initial_state(AcceptMode.AUTO_MEDIUM), thread)

    assert final["op_graph"] is op_graph
    assert final.get("approved") is False  # never visited await_human


def test_auto_medium_requires_human_for_high_risk():
    plan = _plan(_step(["background_replace"], [{"prompt": "forest"}]))
    op_graph = _high_risk_op_graph()
    thread = {"configurable": {"thread_id": "t_am2"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        graph.invoke(_initial_state(AcceptMode.AUTO_MEDIUM), thread)

    assert graph.get_state(thread).next == ("await_human",)


def test_auto_low_requires_human_for_medium_risk():
    plan = _plan(_step(["region_edit"], [{"prompt": "blur"}]))
    op_graph = _medium_risk_op_graph()
    thread = {"configurable": {"thread_id": "t_am3"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        graph.invoke(_initial_state(AcceptMode.AUTO_LOW), thread)

    assert graph.get_state(thread).next == ("await_human",)


# ---------------------------------------------------------------------------
# State shape — plan and op_graph set after first invoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accept_mode,op_graph_fn",
    [
        (AcceptMode.MANUAL, _high_risk_op_graph),  # manual — always interrupts
        (AcceptMode.AUTO_LOW, _high_risk_op_graph),  # auto + high-risk — interrupts
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


# ---------------------------------------------------------------------------
# T3 — auto-approve applies after plan revision (B6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accept_mode,op_graph_fn,expect_interrupt",
    [
        (AcceptMode.FULL_AUTO, _high_risk_op_graph, False),  # always skips
        (AcceptMode.AUTO_LOW, _low_risk_op_graph, False),  # low risk → skips
        (AcceptMode.AUTO_LOW, _medium_risk_op_graph, True),  # medium risk → pauses
        (AcceptMode.AUTO_MEDIUM, _medium_risk_op_graph, False),  # medium risk → skips
    ],
)
def test_auto_approve_after_revision(accept_mode, op_graph_fn, expect_interrupt):
    """After revision, _route_after_compile respects accept_mode (T3 / B6 coverage)."""
    plan_v1 = _plan(_step(["denoise"]))
    plan_v2 = _plan(_step(["exposure"], [{"ev": 1.0}]))
    op_graph = op_graph_fn()
    thread = {"configurable": {"thread_id": f"t3-{accept_mode.value}-{op_graph_fn.__name__}"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan_v1
        mock_planner_cls.return_value.revise.return_value = plan_v2
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )

        # Force the graph through await_human regardless of accept_mode on the first pass
        # by using MANUAL for the first invoke, then resume with feedback to trigger revision.
        # On the revision compile, the state's accept_mode determines the routing.
        state = _initial_state(AcceptMode.MANUAL)
        state["accept_mode"] = accept_mode  # set actual mode before invoke
        graph.invoke(state, thread)

        # At this point the graph is at await_human (MANUAL would interrupt; auto modes may
        # have already ended). For modes that auto-approved on generate, we can't test
        # revision routing via the same thread — test via a fresh MANUAL-first thread.
        if graph.get_state(thread).next != ("await_human",):
            # The mode auto-approved on generate; start fresh, force manual first pass.
            thread2 = {
                "configurable": {
                    "thread_id": f"t3-manual-{accept_mode.value}-{op_graph_fn.__name__}"
                }
            }
            graph2 = build_edit_graph()
            manual_state = _initial_state(AcceptMode.MANUAL)
            graph2.invoke(manual_state, thread2)
            # Now update accept_mode in state and send feedback to trigger revision
            graph2.update_state(thread2, {"accept_mode": accept_mode})
            graph2.invoke(Command(resume={"approved": False, "feedback": "brighter"}), thread2)
            next_nodes = graph2.get_state(thread2).next
        else:
            # Interrupted normally; send feedback to trigger revision
            graph.invoke(Command(resume={"approved": False, "feedback": "brighter"}), thread)
            next_nodes = graph.get_state(thread).next

    if expect_interrupt:
        assert next_nodes == (
            "await_human",
        ), f"{accept_mode} + {op_graph_fn.__name__} should interrupt after revision"
    else:
        assert (
            next_nodes == ()
        ), f"{accept_mode} + {op_graph_fn.__name__} should auto-approve after revision"


# ---------------------------------------------------------------------------
# AGT-B3 — framing_intent forwarded from state into Planner calls
# ---------------------------------------------------------------------------


def test_generate_plan_forwards_framing_intent():
    plan = _plan(_step(["crop"], [{"left": 0, "top": 0, "right": 10, "bottom": 10}]))
    op_graph = _low_risk_op_graph()
    framing = FramingIntent(mode=FramingMode.RULE_OF_THIRDS)
    thread = {"configurable": {"thread_id": "t-framing-1"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
        patch("vlm_photo_editor.ops.executor.Executor") as mock_executor_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)
        mock_executor_cls.return_value.apply.return_value = MagicMock(
            container=_make_container(), genai_ops=[]
        )

        state = _initial_state(AcceptMode.FULL_AUTO)
        state["framing_intent"] = framing
        graph.invoke(state, thread)

        assert mock_planner_cls.return_value.plan.call_args.kwargs["framing_intent"] is framing


def test_revise_plan_forwards_framing_intent():
    plan_v1 = _plan(_step(["denoise"]))
    plan_v2 = _plan(_step(["exposure"], [{"ev": 1.0}]))
    op_graph = _low_risk_op_graph()
    framing = FramingIntent(mode=FramingMode.RULE_OF_THIRDS)
    thread = {"configurable": {"thread_id": "t-framing-2"}}
    graph = build_edit_graph()

    with (
        patch("vlm_photo_editor.agents.edit_flow.Planner") as mock_planner_cls,
        patch("vlm_photo_editor.agents.edit_flow.Compiler") as mock_compiler_cls,
    ):
        mock_planner_cls.return_value.plan.return_value = plan_v1
        mock_planner_cls.return_value.revise.return_value = plan_v2
        mock_compiler_cls.return_value.compile.return_value = _compile_result(op_graph)

        state = _initial_state(AcceptMode.MANUAL)
        state["framing_intent"] = framing
        graph.invoke(state, thread)
        graph.invoke(Command(resume={"approved": False, "feedback": "brighter"}), thread)

        assert mock_planner_cls.return_value.revise.call_args.kwargs["framing_intent"] == framing
