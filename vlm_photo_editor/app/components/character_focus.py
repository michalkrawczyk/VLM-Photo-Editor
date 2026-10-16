"""Character Focus controls (subject-detection model + target classes), shared by panels."""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state

_TARGETS_KEY = "character_focus_targets"  # multiselect widget key; read by main.py detection
_TARGETS_SAVED_KEY = "character_focus_targets_saved"  # survives the widget being unrendered


def no_human_model(model_id: str) -> bool:
    """True for a model with an enumerable vocabulary but neither a person nor a face class.

    Human-oriented edits (portraits) have nothing to anchor on with such a model.
    """
    from vlm_photo_editor.detection import model_has_label, model_labels, model_person_labels

    if model_id == "off":
        return False
    return model_labels(model_id) is not None and not (
        model_person_labels(model_id) or model_has_label(model_id, "face")
    )


def render_character_focus_controls(key: str = "character_focus_select") -> str:
    """Model selector + target classes + Person preset + no-person warning.

    Returns the chosen model id (``"off"`` when none). ``key`` must differ per panel; the
    chosen model lives in ``state["character_focus"]`` and the targets in the shared
    ``character_focus_targets`` widget key, mirrored to a shadow key so they survive a
    run where the panel (and its widget) was not rendered.

    Only models usable now (package importable, file + classes present) are offered; the
    rest would raise a misconfiguration error the moment a plan is generated. Render this
    before the Composition selector so a just-changed model gates face_only this run.
    """
    from vlm_photo_editor.detection import model_labels, model_person_labels, ready_models

    models = {m.id: m for m in ready_models()}
    options = ["off", *models]
    current = state.get("character_focus") or "off"
    if current not in options:
        current = "off"

    def _label(model_id: str) -> str:
        m = models.get(model_id)
        if m is None or m.origin == "legacy":
            return model_id
        return f"{m.display_name} ({m.backend.value})"

    chosen = st.selectbox(
        "Character Focus:",
        options=options,
        index=options.index(current),
        key=key,
        format_func=_label,
    )
    if chosen != state.get("character_focus"):
        # Class ids are per-model: a stale selection would name classes the new model lacks.
        st.session_state[_TARGETS_KEY] = []
        st.session_state[_TARGETS_SAVED_KEY] = []
    state.set("character_focus", chosen)

    if chosen == "off":
        return chosen

    labels = model_labels(chosen)
    if labels is None:
        st.caption("Class-agnostic detector — no class list to choose from.")
        return chosen

    classes = [n for n in dict.fromkeys(labels) if n.strip()]
    if _TARGETS_KEY not in st.session_state:  # widget was unrendered last run: restore
        saved = st.session_state.get(_TARGETS_SAVED_KEY) or []
        st.session_state[_TARGETS_KEY] = [n for n in saved if n in classes]

    person = model_person_labels(chosen)

    def _set_targets(names: list[str]) -> None:
        st.session_state[_TARGETS_KEY] = names

    st.multiselect(
        "Target classes (none = any class):",
        options=classes,
        key=_TARGETS_KEY,
        help=f"{len(classes)} classes in this model.",
    )
    if person:
        st.button(
            "Person preset",
            key="character_focus_person_preset",
            on_click=_set_targets,
            args=(person,),
        )
    if no_human_model(chosen):
        st.warning(
            "This model has no person/face class — it may not work for "
            "portraits or other human-oriented edits."
        )
    st.session_state[_TARGETS_SAVED_KEY] = list(st.session_state.get(_TARGETS_KEY) or [])
    return chosen
