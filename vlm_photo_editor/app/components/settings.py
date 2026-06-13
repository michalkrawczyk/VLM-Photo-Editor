"""Masked API-key entry, role→model switchers, and mode buttons.

Contract:
  - API key inputs: password type; key never stored in session state.
    Logs masked version only. Real storage wired to SecretStore in P7.
  - Model selectors: log intent with role + model; selection stored in state['model_roles'].
"""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.app.stubs import AVAILABLE_MODELS, MODEL_ROLES, PROVIDERS
from vlm_photo_editor.secrets.store import SecretStore


def render() -> None:
    st.subheader("Settings [STUB]")

    with st.expander("API Keys", expanded=False):
        st.caption("Keys are masked and never stored in session state.")
        for provider in PROVIDERS:
            key_input = st.text_input(
                f"{provider.capitalize()} API Key",
                type="password",
                placeholder=f"Enter {provider} API key...",
                key=f"api_key_{provider}",
            )
            if key_input:
                masked = SecretStore.mask(key_input)
                st.caption(f"Masked: {masked}")
                state.log_intent("api_key_entered", {"provider": provider, "masked": masked})

    with st.expander("Model Selection", expanded=True):
        model_roles: dict[str, str] = state.get("model_roles") or {}
        for role in MODEL_ROLES:
            selected = st.selectbox(
                f"{role.replace('_', ' ').title()}:",
                options=AVAILABLE_MODELS,
                index=0,
                key=f"model_{role}",
            )
            model_roles[role] = selected
            state.log_intent("model_selected", {"role": role, "model": selected})
        state.set("model_roles", model_roles)
