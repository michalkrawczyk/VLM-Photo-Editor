"""Masked API-key entry, role→model switchers, and mode buttons.

Contract:
  - API key inputs: password type; key stored in OS keyring via SecretStore.set_in_keyring(),
    never written to session state.
  - Model selectors: call get_registry().set(role, model) immediately so the next
    Planner/build_client call picks up the change.
"""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.app.stubs import AVAILABLE_MODELS, MODEL_ROLES, PROVIDERS
from vlm_photo_editor.config.registry import get_registry
from vlm_photo_editor.secrets.store import SecretStore


def render() -> None:
    st.subheader("Settings")

    with st.expander("API Keys", expanded=False):
        st.caption("Keys saved to OS keyring. Never stored in session state.")
        for provider in PROVIDERS:
            key_input = st.text_input(
                f"{provider.capitalize()} API Key",
                type="password",
                placeholder=f"Enter {provider} API key...",
                key=f"api_key_{provider}",
            )
            if key_input:
                masked = SecretStore.mask(key_input)
                st.caption(f"Saved (masked): {masked}")
                try:
                    SecretStore.set_in_keyring(provider, key_input)
                    state.log_intent("api_key_saved", {"provider": provider, "masked": masked})
                except Exception as exc:
                    st.warning(f"Keyring unavailable: {exc}. Key valid for this session only.")
                    import os

                    os.environ[f"{provider.upper()}_API_KEY"] = key_input
                    state.log_intent("api_key_env_fallback", {"provider": provider})

    with st.expander("Model Selection", expanded=True):
        registry = get_registry()
        model_roles: dict[str, str] = state.get("model_roles") or {}
        for role in MODEL_ROLES:
            current = model_roles.get(role, AVAILABLE_MODELS[0])
            try:
                idx = AVAILABLE_MODELS.index(current)
            except ValueError:
                idx = 0
            selected = st.selectbox(
                f"{role.replace('_', ' ').title()}:",
                options=AVAILABLE_MODELS,
                index=idx,
                key=f"model_{role}",
            )
            if selected != model_roles.get(role):
                registry.set(role, selected)
                model_roles[role] = selected
                state.log_intent("model_selected", {"role": role, "model": selected})
        state.set("model_roles", model_roles)
