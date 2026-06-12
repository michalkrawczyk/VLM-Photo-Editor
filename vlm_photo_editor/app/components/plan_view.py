"""Plan display with expandable compiled ops per step.

Contract:
  - Receives HumanPlan + optional OpGraph (stub or real).
  - Accept button sets state['plan_approved'] = True and logs intent.
  - Change request input logs intent with the request text; would regenerate plan in P7.
"""
from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.schema.ops import OpGraph
from vlm_photo_editor.schema.plan import HumanPlan


def render(plan: HumanPlan, op_graph: OpGraph | None = None) -> None:
    st.subheader("Proposed Plan [STUB]")

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

    st.divider()
    col_acc, col_chg = st.columns(2)
    with col_acc:
        if st.button("Accept Plan", type="primary", key="accept_plan_btn"):
            state.set("plan_approved", True)
            state.log_intent("accept_plan", {"plan_id": plan.plan_id})
            st.success("Plan accepted. [STUB — execution wired in P7]")

    with col_chg:
        change = st.text_input("Request changes:", key="change_request_input")
        if st.button("Request Changes", key="request_changes_btn") and change:
            state.set("change_request", change)
            state.set("plan_approved", False)
            state.log_intent("request_changes", {"change": change})
            st.info(f"Change queued: {change!r} [STUB — would regenerate plan]")
