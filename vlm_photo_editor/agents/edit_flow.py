from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from vlm_photo_editor.agents.planner import Planner
from vlm_photo_editor.planner.compiler import Compiler
from vlm_photo_editor.schema.ops import AcceptMode, OpGraph, RiskTier
from vlm_photo_editor.schema.plan import HumanPlan


class EditState(TypedDict):
    container: Any  # ImageContainer at runtime; Any avoids runtime imageio import
    intent: str
    mode: str  # edit mode: "full" | "background" | "frame"
    accept_mode: AcceptMode  # manual | auto (low-risk skip) | full_auto (always skip)
    prefs: Any | None  # Preferences at runtime
    plan: HumanPlan | None
    op_graph: OpGraph | None
    feedback: str | None
    approved: bool


# --- nodes ---


def _generate_plan(state: EditState) -> dict:
    plan = Planner().plan(state["container"], state["intent"], state.get("prefs"), state["mode"])
    return {"plan": plan, "feedback": None, "approved": False}


def _revise_plan(state: EditState) -> dict:
    plan = Planner().revise(
        state["container"],
        state["plan"],
        state["feedback"],
        state.get("prefs"),
        state["mode"],
    )
    return {"plan": plan, "feedback": None, "approved": False}


def _compile(state: EditState) -> dict:
    result = Compiler().compile(state["plan"], state["mode"])
    return {"op_graph": result.op_graph}


def _await_human(state: EditState) -> dict:
    """Interrupt graph. Resume by passing {"approved": bool, "feedback": str | None}."""
    decision: dict = interrupt({"plan": state["plan"], "op_graph": state["op_graph"]})
    return {"approved": decision.get("approved", False), "feedback": decision.get("feedback")}


def _execute(state: EditState) -> dict:
    # Wired in P7.
    return {}


# --- routing ---


def _can_auto_approve(op_graph: OpGraph | None, mode: AcceptMode) -> bool:
    if not op_graph:
        return False
    if mode == AcceptMode.FULL_AUTO:
        return True
    if mode == AcceptMode.AUTO_MEDIUM:
        return all(op.risk_tier in (RiskTier.LOW, RiskTier.MEDIUM) for op in op_graph.ops)
    if mode == AcceptMode.AUTO_LOW:
        return all(op.risk_tier == RiskTier.LOW for op in op_graph.ops)
    return False


def _route_after_compile(state: EditState) -> str:
    if _can_auto_approve(state.get("op_graph"), state.get("accept_mode")):
        return "execute"
    return "await_human"


def _route_after_human(state: EditState) -> str:
    return "execute" if state.get("approved") else "revise_plan"


# --- graph ---


def build_edit_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = InMemorySaver()

    g = StateGraph(EditState)
    g.add_node("generate_plan", _generate_plan)
    g.add_node("revise_plan", _revise_plan)
    g.add_node("compile", _compile)
    g.add_node("await_human", _await_human)
    g.add_node("execute", _execute)

    g.set_entry_point("generate_plan")
    g.add_edge("generate_plan", "compile")
    g.add_conditional_edges("compile", _route_after_compile)
    g.add_conditional_edges("await_human", _route_after_human)
    g.add_edge("revise_plan", "compile")
    g.add_edge("execute", END)

    return g.compile(checkpointer=checkpointer)


edit_graph = build_edit_graph()
