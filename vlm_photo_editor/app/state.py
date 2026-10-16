"""Session state management. No secrets stored here."""

from __future__ import annotations

from typing import Any

import streamlit as st

_DEFAULTS: dict[str, Any] = {
    "uploaded_file": None,
    "uploaded_files": None,
    "current_file_index": 0,
    "batch_mode": False,
    "batch_records": None,
    "batch_view_index": 0,  # image shown in the batch results viewer
    "batch_retry_id": None,
    "batch_apply_all": True,  # the mode checkbox; default ON = Mode A
    "batch_per_intents": {},  # Mode B: {filename: instruction}
    "output_format": "same",
    "source_name": None,  # original upload filename, for output/recipe naming
    "container": None,  # ImageContainer after loading the uploaded file
    "edited_container": None,  # ImageContainer after Executor.apply()
    "genai_candidates": None,  # step_id -> list[ScoredCandidate] from the last execution
    "genai_override": None,  # step_id -> candidate index chosen by the user
    "current_plan": None,
    "current_opgraph": None,
    "accept_mode": "manual",
    "edit_mode": "full",
    "framing_mode": "rule_of_thirds",
    "bbox": None,
    "change_request": "",
    "plan_approved": False,
    "prefs": None,
    "model_roles": {},
    "intent_log": [],
    "intent": "",
    "ui_phase": "idle",  # idle | has_image | plan_ready | done
    "error": None,
    "saved_path": None,
    "saved_bytes": None,
    "saved_name": None,
    "_loaded_file_id": None,
}


def init_state() -> None:
    for key, value in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Once per session: reap scratch dirs orphaned by past sessions (B5). Local
    # import — tmp_layout imports this module.
    if not st.session_state.get("_stale_swept"):
        from vlm_photo_editor.app.tmp_layout import sweep_stale

        sweep_stale()
        st.session_state["_stale_swept"] = True


def get(key: str) -> Any:
    return st.session_state.get(key)


def set(key: str, value: Any) -> None:  # noqa: A001
    st.session_state[key] = value


def log_intent(action: str, payload: dict[str, Any] | None = None) -> None:
    entry = {"action": action, "payload": payload or {}}
    st.session_state.setdefault("intent_log", []).append(entry)
