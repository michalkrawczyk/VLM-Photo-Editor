"""Streamlit entrypoint. Run: streamlit run vlm_photo_editor/app/main.py"""

import tempfile
from pathlib import Path

import streamlit as st

# Redaction filter must be installed before any logging occurs.
from vlm_photo_editor.secrets.redaction import install_redaction_filter

install_redaction_filter()

from vlm_photo_editor.app import state  # noqa: E402
from vlm_photo_editor.app.components import canvas  # noqa: E402
from vlm_photo_editor.app.components import plan_view  # noqa: E402
from vlm_photo_editor.app.components import prefs_panel  # noqa: E402
from vlm_photo_editor.app.components import preview  # noqa: E402
from vlm_photo_editor.app.components import upload  # noqa: E402
from vlm_photo_editor.app.components import settings as settings_component  # noqa: E402
from vlm_photo_editor.app.stubs import MOCK_PREFS  # noqa: E402
from vlm_photo_editor.schema.ops import AcceptMode, BoundingBox, FramingMode  # noqa: E402

st.set_page_config(
    page_title="VLM Photo Editor",
    layout="wide",
)

state.init_state()

# ── Backend helpers ────────────────────────────────────────────────────────────


def _load_uploaded(file) -> "ImageContainer":  # type: ignore[name-defined]
    from vlm_photo_editor.imageio.loaders import load

    suffix = Path(file.name).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.getvalue())
        tmp_path = Path(tmp.name)
    return load(tmp_path)


def _do_generate_plan() -> None:
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError

    container = state.get("container")
    intent = state.get("intent") or ""
    mode = state.get("edit_mode") or "full"
    prefs = state.get("prefs")

    try:
        plan = Planner().plan(container, intent, prefs, mode)
        result = Compiler().compile(plan, mode)
        state.set("current_plan", result.plan)
        state.set("current_opgraph", result.op_graph)
        state.set("ui_phase", "plan_ready")
        state.set("error", None)
        state.set("plan_approved", False)
    except Exception as exc:
        state.set("error", str(exc))
        state.set("ui_phase", "has_image")


def _do_revise_plan(change: str) -> None:
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.planner.compiler import Compiler

    container = state.get("container")
    previous_plan = state.get("current_plan")
    mode = state.get("edit_mode") or "full"
    prefs = state.get("prefs")

    try:
        plan = Planner().revise(container, previous_plan, change, prefs, mode)
        result = Compiler().compile(plan, mode)
        state.set("current_plan", result.plan)
        state.set("current_opgraph", result.op_graph)
        state.set("change_request", "")
        state.set("plan_approved", False)
        state.set("error", None)
    except Exception as exc:
        state.set("error", str(exc))


def _do_execute() -> None:
    from vlm_photo_editor.ops.executor import Executor
    from vlm_photo_editor.schema.ops import OpGraph

    container = state.get("container")
    op_graph: OpGraph = state.get("current_opgraph")
    bbox_raw = state.get("bbox")

    # Inject bbox into region-targeted ops if one was drawn.
    if bbox_raw and bbox_raw.get("width", 0) > 0 and bbox_raw.get("height", 0) > 0:
        bbox = BoundingBox(
            x=bbox_raw["x"],
            y=bbox_raw["y"],
            width=bbox_raw["width"],
            height=bbox_raw["height"],
        )
        from vlm_photo_editor.schema.ops import OpName

        _REGION_OPS = {OpName.BACKGROUND_REPLACE, OpName.REGION_EDIT, OpName.MASK}
        patched_ops = [
            op.model_copy(update={"bbox": bbox}) if op.op_name in _REGION_OPS else op
            for op in op_graph.ops
        ]
        op_graph = op_graph.model_copy(update={"ops": patched_ops})

    try:
        result = Executor().apply(container, op_graph)
        state.set("edited_container", result.container)
        state.set("ui_phase", "done")
        state.set("error", None)
        state.log_intent("execute", {"ops": len(op_graph.ops)})
    except Exception as exc:
        state.set("error", str(exc))


def _do_save() -> None:
    from vlm_photo_editor.imageio.savers import save as _save
    from vlm_photo_editor.recipe.store import RecipeStore
    from vlm_photo_editor.schema.recipe import Recipe

    edited = state.get("edited_container")
    op_graph = state.get("current_opgraph")
    source = edited.source_path

    dest = source.parent / f"{source.stem}_edited{source.suffix}"
    try:
        saved = _save(edited, dest)
        state.set("saved_path", str(saved))

        recipe = Recipe(source_path=str(source), op_graph=op_graph)
        RecipeStore.save(recipe, directory=source.parent)

        state.log_intent("save", {"path": str(saved)})
        state.set("error", None)
    except Exception as exc:
        state.set("error", str(exc))


# ── Process pending backend actions (before rendering) ────────────────────────

# Read from widget key — Streamlit pre-populates it before the script runs,
# so this works even though upload.render() hasn't executed yet on this pass.
uploaded_file = st.session_state.get("upload_widget") or state.get("uploaded_file")
if uploaded_file is not None:
    state.set("uploaded_file", uploaded_file)

# Auto-load newly uploaded image.
if uploaded_file is not None and state.get("container") is None:
    with st.spinner("Loading image…"):
        try:
            container = _load_uploaded(uploaded_file)
            state.set("container", container)
            state.set("ui_phase", "has_image")
            state.set("edited_container", None)
            state.set("current_plan", None)
            state.set("current_opgraph", None)
            state.set("saved_path", None)
        except Exception as exc:
            state.set("error", str(exc))

# When upload widget resets (new file), reset container too.
if uploaded_file is None and state.get("container") is not None:
    state.set("container", None)
    state.set("edited_container", None)
    state.set("current_plan", None)
    state.set("current_opgraph", None)
    state.set("ui_phase", "idle")
    state.set("saved_path", None)

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
        options=[m.value for m in AcceptMode],
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

    st.subheader("Framing Mode")
    framing = st.selectbox(
        "Composition:",
        options=[m.value for m in FramingMode],
        key="framing_mode_select",
    )
    state.set("framing_mode", framing)

    st.divider()
    settings_component.render()

with main_col:
    # Error banner
    if state.get("error"):
        st.error(state.get("error"))

    ui_phase = state.get("ui_phase") or "idle"

    # Before/after preview
    container = state.get("container")
    edited = state.get("edited_container")
    preview.render(
        before=container.pixels if container else None,
        after=edited.pixels if edited else None,
    )

    st.divider()

    # Intent input + plan generation
    if ui_phase in ("has_image", "plan_ready", "done"):
        intent_val = state.get("intent") or ""
        intent = st.text_input(
            "What would you like to do with this image?",
            value=intent_val,
            key="intent_input",
        )
        state.set("intent", intent)

        col_gen, col_regen = st.columns([1, 1])
        with col_gen:
            generate_label = "Generate Plan" if ui_phase == "has_image" else "Regenerate Plan"
            if st.button(generate_label, key="generate_plan_btn", disabled=not intent):
                with st.spinner("Generating plan…"):
                    _do_generate_plan()
                st.rerun()

    st.divider()

    # BBox canvas — show when image is loaded
    if ui_phase in ("has_image", "plan_ready", "done"):
        canvas.render()
        st.divider()

    # Plan view + accept/change flow
    current_plan = state.get("current_plan")
    current_opgraph = state.get("current_opgraph")

    if ui_phase in ("plan_ready", "done") and current_plan is not None:
        plan_view.render(current_plan, current_opgraph)

        # Handle Accept Plan
        if state.get("plan_approved") and ui_phase != "done":
            with st.spinner("Executing plan…"):
                _do_execute()
            state.set("plan_approved", False)
            st.rerun()

        # Handle Change Request
        change = state.get("change_request") or ""
        if change:
            with st.spinner("Revising plan…"):
                _do_revise_plan(change)
            st.rerun()

    elif ui_phase == "idle":
        st.info("Upload an image to begin.")

    st.divider()
    prefs = state.get("prefs") or MOCK_PREFS
    prefs_panel.render(prefs)

# ── Save button ───────────────────────────────────────────────────────────────
st.divider()
col_save, col_status = st.columns([1, 3])
with col_save:
    can_save = state.get("edited_container") is not None
    if st.button("Save New File", type="primary", key="save_btn", disabled=not can_save):
        with st.spinner("Saving…"):
            _do_save()
        saved = state.get("saved_path")
        if saved:
            st.success(f"Saved: {saved}")

with col_status:
    mode_display = state.get("edit_mode") or "full"
    accept_display = state.get("accept_mode") or "manual"
    phase_display = state.get("ui_phase") or "idle"
    saved_path = state.get("saved_path")
    status_parts = [
        f"Mode: **{mode_display}**",
        f"Accept: **{accept_display}**",
        f"Phase: **{phase_display}**",
    ]
    if saved_path:
        status_parts.append(f"Saved: `{saved_path}`")
    st.caption(" | ".join(status_parts))

# ── Intent log (debug) ────────────────────────────────────────────────────────
with st.expander("Intent Log (debug)", expanded=False):
    log = state.get("intent_log") or []
    for entry in reversed(log):
        st.write(entry)
