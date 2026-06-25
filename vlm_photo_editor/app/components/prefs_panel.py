"""Explicit + learned preferences panel with per-rule toggles.

Contract:
  - Displays ExplicitRule and LearnedRule lists from Preferences.
  - Mutations write through PreferenceStore and update session state.
"""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.preferences.store import PreferenceStore
from vlm_photo_editor.schema.prefs import Preferences


def _ps() -> PreferenceStore:
    return PreferenceStore()


def render(prefs: Preferences) -> None:
    st.subheader("Preferences")

    with st.expander("Explicit Rules", expanded=True):
        if not prefs.explicit:
            st.caption("No explicit rules yet.")
        for rule in prefs.explicit:
            col_t, col_tog, col_rm = st.columns([5, 1, 1])
            with col_t:
                st.write(f"{'[on]' if rule.active else '[off]'} {rule.description}")
            with col_tog:
                toggle_label = "Disable" if rule.active else "Enable"
                if st.button(toggle_label, key=f"tog_explicit_{rule.rule_id}"):
                    _ps().toggle_rule(rule.rule_id)
                    state.set("prefs", _ps().load())
                    state.log_intent("toggle_explicit_rule", {"rule_id": rule.rule_id})
                    st.rerun()
            with col_rm:
                if st.button("Remove", key=f"rm_explicit_{rule.rule_id}"):
                    _ps().remove_explicit(rule.rule_id)
                    state.set("prefs", _ps().load())
                    state.log_intent("remove_explicit_rule", {"rule_id": rule.rule_id})
                    st.rerun()

        new_rule = st.text_input("Add explicit rule:", key="new_explicit_rule_input")
        if st.button("Add Rule", key="add_explicit_btn") and new_rule:
            _ps().add_explicit(new_rule)
            state.set("prefs", _ps().load())
            state.log_intent("add_explicit_rule", {"description": new_rule})
            st.rerun()

    with st.expander("Learned Rules", expanded=False):
        pending = [r for r in prefs.learned if not r.approved]
        active = [r for r in prefs.learned if r.approved]

        if pending:
            st.caption(f"{len(pending)} candidate(s) awaiting approval:")
            for rule in pending:
                col_t, col_approve, col_rm = st.columns([5, 1, 1])
                with col_t:
                    st.write(f"[pending] {rule.description} (confidence: {rule.confidence:.0%})")
                with col_approve:
                    if st.button("Approve", key=f"approve_{rule.rule_id}"):
                        _ps().approve_learned(rule.rule_id)
                        state.set("prefs", _ps().load())
                        state.log_intent("approve_learned_rule", {"rule_id": rule.rule_id})
                        st.rerun()
                with col_rm:
                    if st.button("Dismiss", key=f"dismiss_{rule.rule_id}"):
                        _ps().remove_explicit(rule.rule_id)  # reuse remove logic
                        state.log_intent("dismiss_learned_rule", {"rule_id": rule.rule_id})
                        st.rerun()

        if not active and not pending:
            st.caption("No learned rules yet. Accept a few edits to generate candidates.")

        for rule in active:
            col_t, col_tog = st.columns([5, 1])
            with col_t:
                status = "active" if rule.active else "inactive"
                st.write(f"[{status}] {rule.description} (confidence: {rule.confidence:.0%})")
            with col_tog:
                toggle_label = "Disable" if rule.active else "Enable"
                if st.button(toggle_label, key=f"tog_learned_{rule.rule_id}"):
                    _ps().toggle_rule(rule.rule_id)
                    state.set("prefs", _ps().load())
                    state.log_intent("toggle_learned_rule", {"rule_id": rule.rule_id})
                    st.rerun()

        if st.button("Run Aggregation Now", key="run_aggregation_btn"):
            state.set("run_aggregation", True)
            state.log_intent("manual_aggregation_triggered", {})
            st.rerun()
