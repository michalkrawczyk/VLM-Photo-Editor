"""Explicit + learned preferences panel with per-rule toggles.

Contract:
  - Displays ExplicitRule and LearnedRule lists from Preferences.
  - All mutations log intent; no real mutation in P0.5 (wired in P8).
"""
from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.schema.prefs import Preferences


def render(prefs: Preferences) -> None:
    st.subheader("Preferences [STUB]")

    with st.expander("Explicit Rules", expanded=True):
        if not prefs.explicit:
            st.caption("No explicit rules yet.")
        for rule in prefs.explicit:
            col_t, col_rm = st.columns([5, 1])
            with col_t:
                st.write(f"{'[on]' if rule.active else '[off]'} {rule.description}")
            with col_rm:
                if st.button("Remove", key=f"rm_explicit_{rule.rule_id}"):
                    state.log_intent("remove_explicit_rule", {"rule_id": rule.rule_id})
                    st.info("[STUB] Would remove rule")

        new_rule = st.text_input("Add explicit rule:", key="new_explicit_rule_input")
        if st.button("Add Rule", key="add_explicit_btn") and new_rule:
            state.log_intent("add_explicit_rule", {"description": new_rule})
            st.info(f"[STUB] Would add: {new_rule!r}")

    with st.expander("Learned Rules", expanded=False):
        if not prefs.learned:
            st.caption("No learned rules yet.")
        for rule in prefs.learned:
            col_t, col_tog = st.columns([5, 1])
            with col_t:
                status = "active" if rule.active else "inactive"
                approved = "approved" if rule.approved else "pending approval"
                st.write(
                    f"[{status}/{approved}] {rule.description} "
                    f"(confidence: {rule.confidence:.0%})"
                )
            with col_tog:
                if st.button("Toggle", key=f"toggle_learned_{rule.rule_id}"):
                    state.log_intent(
                        "toggle_learned_rule",
                        {"rule_id": rule.rule_id, "currently_active": rule.active},
                    )
                    st.info("[STUB] Would toggle rule")
