"""Streamlit entrypoint. Run: streamlit run vlm_photo_editor/app/main.py"""
import streamlit as st

# Redaction filter must be installed before any logging occurs.
from vlm_photo_editor.secrets.redaction import install_redaction_filter

install_redaction_filter()

from vlm_photo_editor.app import state  # noqa: E402
from vlm_photo_editor.app import stubs  # noqa: E402
from vlm_photo_editor.app.components import canvas  # noqa: E402
from vlm_photo_editor.app.components import plan_view  # noqa: E402
from vlm_photo_editor.app.components import prefs_panel  # noqa: E402
from vlm_photo_editor.app.components import preview  # noqa: E402
from vlm_photo_editor.app.components import settings as settings_component  # noqa: E402
from vlm_photo_editor.app.components import upload  # noqa: E402
from vlm_photo_editor.schema.ops import FramingMode  # noqa: E402

st.set_page_config(
    page_title="VLM Photo Editor",
    layout="wide",
)

state.init_state()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("VLM Photo Editor")
st.caption("Propose → Approve → Apply. Originals are never altered.")

# ── Top controls bar ──────────────────────────────────────────────────────────
col_bg, col_frame, col_full, col_accept = st.columns([1, 1, 1, 2])
with col_bg:
    if st.button("Background Only", key="mode_bg"):
        state.set("edit_mode", "background")
        state.log_intent("mode_change", {"mode": "background"})
with col_frame:
    if st.button("Frame Only", key="mode_frame"):
        state.set("edit_mode", "frame")
        state.log_intent("mode_change", {"mode": "frame"})
with col_full:
    if st.button("Full Edit", key="mode_full"):
        state.set("edit_mode", "full")
        state.log_intent("mode_change", {"mode": "full"})
with col_accept:
    accept_mode = st.radio(
        "Accept mode:",
        options=["manual", "auto"],
        horizontal=True,
        key="accept_mode_radio",
    )
    state.set("accept_mode", accept_mode)

st.divider()

# ── Main layout ───────────────────────────────────────────────────────────────
sidebar_col, main_col = st.columns([1, 2])

with sidebar_col:
    upload.render()
    st.divider()

    st.subheader("Framing Mode [STUB]")
    framing = st.selectbox(
        "Composition:",
        options=[m.value for m in FramingMode],
        key="framing_mode_select",
    )
    state.set("framing_mode", framing)
    state.log_intent("framing_mode_change", {"mode": framing})

    st.divider()
    settings_component.render()

with main_col:
    preview.render()
    st.divider()
    canvas.render()
    st.divider()
    plan_view.render(stubs.MOCK_PLAN, stubs.MOCK_OPGRAPH)
    st.divider()
    prefs_panel.render(stubs.MOCK_PREFS)

# ── Save button ───────────────────────────────────────────────────────────────
st.divider()
col_save, col_status = st.columns([1, 3])
with col_save:
    if st.button("Save New File", type="primary", key="save_btn"):
        state.log_intent("save", {})
        st.success("[STUB] Would write a new file. Original untouched.")
with col_status:
    mode_display = state.get("edit_mode") or "full"
    accept_display = state.get("accept_mode") or "manual"
    st.caption(
        f"Mode: **{mode_display}** | Accept: **{accept_display}** "
        "| All processing is stubbed — P7 wires real logic"
    )

# ── Intent log (debug) ────────────────────────────────────────────────────────
with st.expander("Intent Log (debug)", expanded=False):
    log = state.get("intent_log") or []
    for entry in reversed(log):
        st.write(entry)
