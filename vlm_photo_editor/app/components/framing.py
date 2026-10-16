"""Composition (framing) controls shared by single-image and batch panels."""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.templates.framing import focus_instruction, frame_ratio_str


def build_framing_intent(framing_val: str) -> FramingIntent:
    from vlm_photo_editor.detection import model_has_label

    mode = FramingMode(framing_val)
    fi = FramingIntent(
        mode=mode,
        focus_instruction=focus_instruction(mode),
        frame_ratio=frame_ratio_str(mode),
        face_framing_allowed=model_has_label(state.get("character_focus") or "off", "face"),
    )
    if mode is FramingMode.RECOMMEND_BEST:
        fi.user_instruction = st.session_state.get("framing_hint") or None
    return fi


def current_framing_intent() -> FramingIntent | None:
    """FramingIntent for the stored composition, or None when none is set."""
    framing_val = state.get("framing_mode")
    return build_framing_intent(framing_val) if framing_val else None


def render_composition_controls(key: str = "framing_mode_select") -> str:
    """Composition selector + headroom warning + guidance box. Returns the chosen mode value.

    ``key`` must differ per panel (Streamlit widget keys are global); every panel writes the
    same ``framing_mode`` state value, so the choice carries over.
    """
    from vlm_photo_editor.app.components.character_focus import no_human_model
    from vlm_photo_editor.detection import model_has_label

    character_focus = state.get("character_focus") or "off"
    no_human = no_human_model(character_focus)

    # face_only is offered only when the active Character Focus model exposes a "face"
    # class; otherwise a stored "face_only" falls back to index 0 (rule_of_thirds).
    stored = state.get("framing_mode") or FramingMode.RULE_OF_THIRDS.value
    face_ok = model_has_label(character_focus, "face")
    options = [m.value for m in FramingMode if m is not FramingMode.FACE_ONLY or face_ok]
    chosen = st.selectbox(
        "Composition:",
        options=options,
        index=options.index(stored) if stored in options else 0,
        key=key,
    )
    state.set("framing_mode", chosen)

    if chosen == FramingMode.PORTRAIT_HEADROOM.value and no_human:
        st.warning(
            "portrait_headroom is person-oriented but the active detector has no "
            "person/face class — the subject box may not be a person."
        )
    if chosen == FramingMode.RECOMMEND_BEST.value:
        st.text_input("Framing guidance (optional)", key="framing_hint")
    return chosen
