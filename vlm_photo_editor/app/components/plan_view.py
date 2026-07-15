"""Plan display with expandable compiled ops per step.

Contract:
  - Receives HumanPlan + optional OpGraph.
  - "Accept Plan" sets state['plan_approved'] = True.
  - "Request Changes" sets state['change_request'] and state['plan_approved'] = False.
  - Execution is triggered by main.py after detecting plan_approved = True.
"""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.schema.ops import OpGraph
from vlm_photo_editor.schema.plan import HumanPlan


def render(plan: HumanPlan, op_graph: OpGraph | None = None, *, executed: bool = False) -> None:
    st.subheader("Proposed Plan")

    ops_by_step: dict[str, list] = {}
    if op_graph:
        for op in op_graph.ops:
            ops_by_step.setdefault(op.step_id, []).append(op)

    for step in plan.steps:
        with st.expander(f"Step {step.index}: {step.title}", expanded=True):
            st.markdown(f"**Why:** {step.why}")
            if step.step_id in ops_by_step:
                st.caption("Compiled ops:")
                for op in ops_by_step[step.step_id]:
                    st.code(
                        f"{op.op_name.value}({op.params})"
                        f" via {op.backend.value} [{op.risk_tier.value} risk]"
                    )

    if op_graph:
        from vlm_photo_editor.ops.constants import INPAINT_OPS as _INPAINT_OPS
        from vlm_photo_editor.schema.ops import Backend as _Backend
        from vlm_photo_editor.schema.ops import OpName as _OpName

        needs_manual_bbox = any(
            op.bbox is None
            and (
                (op.backend == _Backend.OPENCV and op.op_name in _INPAINT_OPS)
                or op.op_name == _OpName.FILL_MASK
                or op.params.get("invert") is True
            )
            for op in op_graph.ops
        )
        bbox = state.get("bbox")
        if needs_manual_bbox and not (bbox and bbox.get("width", 0) > 0):
            st.warning(
                "This plan requires a region selection (OpenCV inpaint, fill_mask, or a "
                "mask step with no detected subject). Expand 'Region Selection (BBox)' "
                "above and draw a rectangle before accepting."
            )

    st.divider()
    col_acc, col_chg = st.columns(2)
    with col_acc:
        if executed:
            st.success("Executed ✓")
        elif op_graph is None:
            st.warning(
                "Plan could not be compiled — see error above. "
                "Use 'Request Changes' to revise, or fix the issue and Regenerate."
            )
        elif st.button("Accept Plan", type="primary", key="accept_plan_btn"):
            state.set("plan_approved", True)
            state.log_intent("accept_plan", {"plan_id": plan.plan_id})

    with col_chg:
        change = st.text_input("Request changes:", key="change_request_input")
        if st.button("Request Changes", key="request_changes_btn") and change:
            state.set("change_request", change)
            state.set("plan_approved", False)
            state.log_intent("request_changes", {"change": change})
