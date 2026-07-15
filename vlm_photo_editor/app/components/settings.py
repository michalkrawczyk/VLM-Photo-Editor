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

_LOADER_DESCRIPTIONS: dict[str, str] = {
    "ollama": "Local Ollama server (CPU/GPU, quantized models)",
    "transformers": "HuggingFace Transformers pipeline (GPU recommended)",
    "llamacpp": "llama.cpp GGUF files inline (CPU-friendly, no server needed)",
    "vllm": "vLLM server — OpenAI-compatible endpoint (GPU, highest throughput)",
}

_CHAR_FOCUS_DESCRIPTIONS: dict[str, str] = {
    "mediapipe": "MediaPipe Object Detector (.tflite, CPU-friendly)",
    "yolo_onnx": "YOLO via ONNX Runtime (.onnx, manual pre/post-processing)",
    "u2netp": "U2-Netp salient-object detector (.onnx, class-agnostic)",
}
_CHAR_FOCUS_PATH_ATTR: dict[str, str] = {
    "mediapipe": "mediapipe_model_path",
    "yolo_onnx": "yolo_onnx_model_path",
    "u2netp": "u2netp_model_path",
}
from vlm_photo_editor.app import state
from vlm_photo_editor.app.stubs import (
    AVAILABLE_MODELS,
    LOCAL_MODEL_IDS,
    MODEL_ROLES,
    PROVIDERS,
    provider_for_model,
)
from vlm_photo_editor.config.registry import (
    AGGREGATOR_PRESETS,
    CRITIC_PRESETS,
    ModelEntry,
    get_registry,
)
from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.secrets.store import SecretStore, _env_key

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
            already_set = SecretStore.has(provider)
            if already_set:
                st.caption(f"✓ {provider.capitalize()} key already set in keyring")
            key_input = st.text_input(
                f"{provider.capitalize()} API Key",
                type="password",
                placeholder=(
                    "Enter new key to update" if already_set else f"Enter {provider} API key..."
                ),
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

                    os.environ[_env_key(provider)] = key_input
                    state.log_intent("api_key_env_fallback", {"provider": provider})

    with st.expander("Model Selection", expanded=True):
        registry = get_registry()
        model_roles: dict[str, str] = state.get("model_roles") or {}

        from vlm_photo_editor.models.registry import model_entry_available

        for role in MODEL_ROLES:
            if role == "preference_aggregator":
                _avail: list[str] = []
                _unavail: dict[str, str] = {}
                for name, entry in AGGREGATOR_PRESETS.items():
                    ok, reason = model_entry_available(entry)
                    if ok:
                        _avail.append(name)
                    else:
                        _unavail[name] = reason

                current_preset = state.get("aggregator_preset") or (_avail[0] if _avail else "")
                if current_preset not in _avail and _avail:
                    st.warning(
                        f"'{current_preset}' unavailable"
                        f" ({_unavail.get(current_preset, 'unknown reason')})."
                        " Select a working model."
                    )
                    current_preset = _avail[0]
                    state.set("aggregator_preset", current_preset)

                if _avail:
                    selected_preset = st.selectbox(
                        "Preference Aggregator:",
                        options=_avail,
                        index=_avail.index(current_preset) if current_preset in _avail else 0,
                        key="model_preference_aggregator",
                    )
                    if selected_preset != current_preset:
                        registry.set_entry(role, AGGREGATOR_PRESETS[selected_preset])
                        state.set("aggregator_preset", selected_preset)
                        state.log_intent(
                            "model_selected", {"role": role, "preset": selected_preset}
                        )
                else:
                    st.error(
                        "No aggregator models available. Add an API key or install a local backend."
                    )

                if _unavail:
                    st.caption(
                        "Not available: " + ", ".join(f"{n} ({r})" for n, r in _unavail.items())
                    )

            elif role == "critic":
                _avail2: list[str] = []
                _unavail2: dict[str, str] = {}
                for name, entry in CRITIC_PRESETS.items():
                    ok, reason = model_entry_available(entry)
                    if ok:
                        _avail2.append(name)
                    else:
                        _unavail2[name] = reason

                current_preset = state.get("critic_preset") or (_avail2[0] if _avail2 else "")
                if current_preset not in _avail2 and _avail2:
                    st.warning(
                        f"'{current_preset}' unavailable"
                        f" ({_unavail2.get(current_preset, 'unknown reason')})."
                        " Select a working model."
                    )
                    current_preset = _avail2[0]
                    state.set("critic_preset", current_preset)

                if _avail2:
                    selected_preset = st.selectbox(
                        "Critic:",
                        options=_avail2,
                        index=_avail2.index(current_preset) if current_preset in _avail2 else 0,
                        key="model_critic",
                    )
                    if selected_preset != current_preset:
                        registry.set_entry(role, CRITIC_PRESETS[selected_preset])
                        state.set("critic_preset", selected_preset)
                        state.log_intent(
                            "model_selected", {"role": role, "preset": selected_preset}
                        )
                else:
                    st.error(
                        "No critic models available. Add an API key or install a local backend."
                    )

                if _unavail2:
                    st.caption(
                        "Not available: " + ", ".join(f"{n} ({r})" for n, r in _unavail2.items())
                    )

            else:
                _avail_m: list[str] = []
                _unavail_m: dict[str, str] = {}
                for m in AVAILABLE_MODELS:
                    provider = provider_for_model(m)
                    me = ModelEntry(
                        m,
                        provider=provider,  # type: ignore[arg-type]
                        loader="transformers" if m in LOCAL_MODEL_IDS else None,
                    )
                    ok, reason = model_entry_available(me)
                    if ok:
                        _avail_m.append(m)
                    else:
                        _unavail_m[m] = reason

                current = model_roles.get(role, _avail_m[0] if _avail_m else "")
                if current not in _avail_m and _avail_m:
                    st.warning(
                        f"'{current}' unavailable"
                        f" ({_unavail_m.get(current, 'unknown reason')})."
                        " Select a working model."
                    )
                    current = _avail_m[0]

                if _avail_m:
                    selected = st.selectbox(
                        f"{role.replace('_', ' ').title()}:",
                        options=_avail_m,
                        format_func=lambda m: f"{m} (local)" if m in LOCAL_MODEL_IDS else m,
                        index=_avail_m.index(current) if current in _avail_m else 0,
                        key=f"model_{role}",
                    )
                    if selected != current:
                        registry.set(role, selected)
                        model_roles[role] = selected
                        state.log_intent("model_selected", {"role": role, "model": selected})
                else:
                    st.error(
                        f"No models available for {role!r}. Add API keys or install a local backend."
                    )

                if _unavail_m:
                    st.caption(
                        "Not available: "
                        + ", ".join(
                            f"{'(local) ' if m in LOCAL_MODEL_IDS else ''}{m} ({r})"
                            for m, r in _unavail_m.items()
                        )
                    )

        state.set("model_roles", model_roles)

        st.divider()
        _GENAI_IMAGE_PRESETS = [
            "black-forest-labs/flux-fill-dev",
            "stability-ai/stable-diffusion-inpainting",
            "openai:dall-e-3",
            "openai:gpt-image-1",
            "google:imagen-3.0-generate-002",
            "hf:stabilityai/stable-diffusion-2-inpainting",
        ]
        from vlm_photo_editor.background.providers import (
            available_genai_providers,
            provider_name_for,
        )

        _avail_providers = set(available_genai_providers())
        _avail_genai = [m for m in _GENAI_IMAGE_PRESETS if provider_name_for(m) in _avail_providers]
        _unavail_genai = [m for m in _GENAI_IMAGE_PRESETS if m not in _avail_genai]

        settings = get_settings()
        current_genai = settings.genai_model
        if _avail_genai:
            try:
                genai_idx = _avail_genai.index(current_genai)
            except ValueError:
                genai_idx = 0
            selected_genai = st.selectbox(
                "GenAI Image Model:",
                options=_avail_genai,
                index=genai_idx,
                key="genai_image_model",
            )
            if selected_genai != current_genai:
                settings.genai_model = selected_genai
                state.log_intent("model_selected", {"role": "genai_image", "model": selected_genai})
        else:
            st.error("No GenAI image backend available. Add an API key or install diffusers.")

        if _unavail_genai:
            st.caption("Not available: " + ", ".join(_unavail_genai))

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

    with st.expander("Local Model Backends", expanded=False):

        @st.cache_data(ttl=60)
        def _loader_status() -> set[str]:
            from vlm_photo_editor.models.registry import available_loaders

            return set(available_loaders())

        ready = _loader_status()
        for loader, desc in _LOADER_DESCRIPTIONS.items():
            col1, col2, col3 = st.columns([2, 4, 1])
            with col1:
                st.write(f"**{loader}**")
            with col2:
                st.caption(desc)
            with col3:
                if loader == "vllm":
                    badge_text = "ready" if loader in ready else "server unreachable"
                else:
                    badge_text = "ready" if loader in ready else "not installed"
                badge_color = "green" if badge_text == "ready" else "red"
                st.markdown(
                    f"<span style='color:{badge_color};font-weight:bold'>{badge_text}</span>",
                    unsafe_allow_html=True,
                )

            if loader == "vllm":
                vllm_url = st.text_input(
                    "vLLM server URL",
                    value="http://localhost:8000/v1",
                    key="vllm_base_url",
                )
                if st.button("Ping", key="vllm_ping"):
                    from vlm_photo_editor.models.registry import _vllm_reachable

                    if _vllm_reachable():
                        st.success("Server reachable.")
                    else:
                        st.error(f"Cannot reach {vllm_url}")
            elif badge_text == "not installed":
                if st.button("Install", key=f"install_{loader}"):
                    with st.spinner(f"Installing {loader} deps…"):
                        from vlm_photo_editor.models.registry import install_loader_deps

                        ok = install_loader_deps(loader)
                    _loader_status.clear()
                    if ok:
                        st.success("Installed. Reload the page to refresh status.")
                    else:
                        st.error("Install failed — check the terminal for details.")

    with st.expander("Character Focus", expanded=False):
        st.caption(
            "Local subject detection (zero API cost). Each backend needs its package "
            "installed and a model file path configured below — no auto-download."
        )

        @st.cache_data(ttl=60)
        def _cf_status() -> set[str]:
            from vlm_photo_editor.detection import available_backends

            return set(available_backends())

        cf_installed = _cf_status()
        cf_settings = get_settings()
        for backend, desc in _CHAR_FOCUS_DESCRIPTIONS.items():
            col1, col2, col3 = st.columns([2, 4, 1])
            with col1:
                st.write(f"**{backend}**")
            with col2:
                st.caption(desc)

            path_attr = _CHAR_FOCUS_PATH_ATTR[backend]
            current_path = getattr(cf_settings, path_attr) or ""
            with col3:
                if backend not in cf_installed:
                    badge_text, badge_color = "package missing", "red"
                elif not current_path:
                    badge_text, badge_color = "path not set", "orange"
                else:
                    badge_text, badge_color = "ready", "green"
                st.markdown(
                    f"<span style='color:{badge_color};font-weight:bold'>{badge_text}</span>",
                    unsafe_allow_html=True,
                )

            if backend not in cf_installed:
                if st.button("Install", key=f"install_cf_{backend}"):
                    with st.spinner(f"Installing {backend} deps…"):
                        from vlm_photo_editor.detection import install_backend_deps

                        ok = install_backend_deps(backend)
                    _cf_status.clear()
                    if ok:
                        st.success("Installed. Reload the page to refresh status.")
                    else:
                        st.error("Install failed — check the terminal for details.")
            else:
                new_path = st.text_input(
                    f"{backend} model path",
                    value=current_path,
                    key=f"cf_path_{backend}",
                )
                if new_path != current_path:
                    setattr(cf_settings, path_attr, new_path or None)
