"""Masked API-key entry, role→model switchers, and mode buttons.

Contract:
  - API key inputs: password type; key stored in OS keyring via SecretStore.set_in_keyring(),
    never written to session state.
  - Model selectors: call get_registry().set(role, model) immediately so the next
    Planner/build_client call picks up the change.
"""

from __future__ import annotations

import socket

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.app.stubs import AVAILABLE_MODELS, LOCAL_MODEL_IDS, MODEL_ROLES, PROVIDERS
from vlm_photo_editor.config.registry import AGGREGATOR_PRESETS, CRITIC_PRESETS, get_registry
from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.secrets.store import SecretStore

_PS_MCP_HOST = "127.0.0.1"
_PS_MCP_PORT = 8080


def _ps_available() -> bool:
    try:
        with socket.create_connection((_PS_MCP_HOST, _PS_MCP_PORT), timeout=0.2):
            return True
    except OSError:
        return False


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
        _aggregator_options = list(AGGREGATOR_PRESETS.keys())
        _critic_options = list(CRITIC_PRESETS.keys())

        for role in MODEL_ROLES:
            if role == "preference_aggregator":
                current_preset = state.get("aggregator_preset") or _aggregator_options[0]
                try:
                    idx = _aggregator_options.index(current_preset)
                except ValueError:
                    idx = 0
                selected_preset = st.selectbox(
                    "Preference Aggregator:",
                    options=_aggregator_options,
                    index=idx,
                    key="model_preference_aggregator",
                )
                if selected_preset != current_preset:
                    registry.set_entry(role, AGGREGATOR_PRESETS[selected_preset])
                    state.set("aggregator_preset", selected_preset)
                    state.log_intent("model_selected", {"role": role, "preset": selected_preset})

            elif role == "critic":
                current_preset = state.get("critic_preset") or _critic_options[0]
                try:
                    idx = _critic_options.index(current_preset)
                except ValueError:
                    idx = 0
                selected_preset = st.selectbox(
                    "Critic:",
                    options=_critic_options,
                    index=idx,
                    key="model_critic",
                )
                if selected_preset != current_preset:
                    registry.set_entry(role, CRITIC_PRESETS[selected_preset])
                    state.set("critic_preset", selected_preset)
                    state.log_intent("model_selected", {"role": role, "preset": selected_preset})

            else:
                current = model_roles.get(role, AVAILABLE_MODELS[0])
                try:
                    idx = AVAILABLE_MODELS.index(current)
                except ValueError:
                    idx = 0
                selected = st.selectbox(
                    f"{role.replace('_', ' ').title()}:",
                    options=AVAILABLE_MODELS,
                    format_func=lambda m: f"{m} (local)" if m in LOCAL_MODEL_IDS else m,
                    index=idx,
                    key=f"model_{role}",
                )
                if selected != model_roles.get(role):
                    registry.set(role, selected)
                    model_roles[role] = selected
                    state.log_intent("model_selected", {"role": role, "model": selected})

        state.set("model_roles", model_roles)

    with st.expander("Photoshop Mode", expanded=False):
        _PS_LABELS = {
            "auto": "Auto (normal)",
            "strict": "PS-strict (Photoshop-expressible ops only)",
            "none": "No-PS (Photoshop backend disabled)",
        }
        settings = get_settings()
        current_ps_mode = settings.ps_mode
        _ps_options = ["auto", "strict", "none"]
        try:
            ps_idx = _ps_options.index(current_ps_mode)
        except ValueError:
            ps_idx = 0
        selected_ps_mode = st.radio(
            "PS Mode:",
            options=_ps_options,
            format_func=_PS_LABELS.get,
            index=ps_idx,
            key="ps_mode_radio",
        )
        if selected_ps_mode != current_ps_mode:
            settings.ps_mode = selected_ps_mode
            state.log_intent("ps_mode_changed", {"mode": selected_ps_mode})
        if selected_ps_mode == "strict" and not _ps_available():
            st.warning(
                "Photoshop not connected. " "Install the PS plugin or switch to 'auto' mode."
            )
