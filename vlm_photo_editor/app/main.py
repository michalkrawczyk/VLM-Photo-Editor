"""Streamlit entrypoint. Run: streamlit run vlm_photo_editor/app/main.py"""

from pathlib import Path

import streamlit as st

# Redaction filter must be installed before any logging occurs.
from vlm_photo_editor.secrets.redaction import install_redaction_filter

install_redaction_filter()

from vlm_photo_editor.app import state  # noqa: E402
from vlm_photo_editor.app.components import batch_review  # noqa: E402
from vlm_photo_editor.app.components import candidate_picker  # noqa: E402
from vlm_photo_editor.app.components import canvas  # noqa: E402
from vlm_photo_editor.app.components import plan_view  # noqa: E402
from vlm_photo_editor.app.components import prefs_panel  # noqa: E402
from vlm_photo_editor.app.components import preview  # noqa: E402
from vlm_photo_editor.app.components import upload  # noqa: E402
from vlm_photo_editor.app.components import settings as settings_component  # noqa: E402
from vlm_photo_editor.preferences.store import (  # noqa: E402
    AGGREGATE_AFTER,
    DeltaStore,
    PreferenceStore,
)
from vlm_photo_editor.schema.ops import (  # noqa: E402
    AcceptMode,
    BoundingBox,
    FramingIntent,
    FramingMode,
)
from vlm_photo_editor.templates.framing import focus_instruction, frame_ratio_str  # noqa: E402

st.set_page_config(
    page_title="VLM Photo Editor",
    layout="wide",
)

state.init_state()

# ── Backend helpers ────────────────────────────────────────────────────────────


def _load_uploaded(file) -> "ImageContainer":  # type: ignore[name-defined]
    from vlm_photo_editor.app.tmp_layout import image_workdir
    from vlm_photo_editor.imageio.loaders import load

    suffix = Path(file.name).suffix
    workdir = image_workdir(Path(file.name).stem)
    src_path = workdir / f"original{suffix}"
    src_path.write_bytes(file.getvalue())
    state.set("source_name", file.name)
    return load(src_path)


def _build_framing_intent(framing_val: str) -> FramingIntent:
    mode = FramingMode(framing_val)
    fi = FramingIntent(
        mode=mode,
        focus_instruction=focus_instruction(mode),
        frame_ratio=frame_ratio_str(mode),
    )
    if mode is FramingMode.RECOMMEND_BEST:
        fi.user_instruction = st.session_state.get("framing_hint") or None
    return fi


def _detect_subject_if_enabled(container: "ImageContainer"):  # type: ignore[name-defined]
    cf_val = state.get("character_focus") or "off"
    if cf_val == "off":
        return None
    from vlm_photo_editor.detection import detect_subject

    return detect_subject(container, cf_val)


def _do_generate_plan() -> None:
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.background.providers import default_provider_available
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.ops.validator import validate_crop_bounds
    from vlm_photo_editor.pipeline.job_queue import run_job
    from vlm_photo_editor.pipeline.plan_cache import get_plan_cache
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError

    container = state.get("container")
    intent = state.get("intent") or ""
    mode = state.get("edit_mode") or "full"
    prefs = state.get("prefs")

    framing_val = state.get("framing_mode")
    fi = _build_framing_intent(framing_val) if framing_val else None
    genai_available = default_provider_available()

    cache = get_plan_cache()
    cache_key = cache.key(container, mode, prefs, intent, framing_val)
    cached_plan = cache.get(cache_key)

    try:
        # Inside the try so a misconfigured Character Focus backend surfaces as an
        # error banner instead of crashing the Streamlit script.
        detected_subject = _detect_subject_if_enabled(container)
        planner = None
        _progress = None
        if cached_plan is not None:
            plan = cached_plan
            state.log_intent("plan_cache_hit", {"key": cache_key})
        else:
            _progress = st.progress(0.0, text="Generating plan…")
            planner = Planner()
            plan = run_job(
                planner.plan, container, intent, prefs, mode, fi, detected_subject, genai_available
            )
            _progress.progress(0.5, text="Compiling…")

        max_retries = get_settings().max_crop_retries
        for _attempt in range(max_retries + 1):
            result = Compiler().compile(plan, mode, detected_subject=detected_subject)
            try:
                validate_crop_bounds(result.op_graph, container.width, container.height)
                break
            except ValueError as crop_err:
                if _attempt >= max_retries:
                    raise
                if planner is None:
                    planner = Planner()
                plan = run_job(
                    planner.revise,
                    container,
                    plan,
                    str(crop_err),
                    prefs,
                    mode,
                    fi,
                    detected_subject,
                    genai_available,
                )

        if cached_plan is None:
            cache.set(cache_key, result.plan)
        if _progress is not None:
            _progress.progress(1.0, text="Done.")

        state.set("current_plan", result.plan)
        state.set("current_opgraph", result.op_graph)
        state.set("initial_plan", result.plan)
        state.set("change_requests_log", [])
        state.set("ui_phase", "plan_ready")
        state.set("error", None)
        from vlm_photo_editor.agents.edit_flow import _can_auto_approve

        _mode = AcceptMode(state.get("accept_mode") or AcceptMode.MANUAL.value)
        state.set("plan_approved", _can_auto_approve(result.op_graph, _mode))
        if result.plan.chosen_framing_mode:
            st.info(
                f"Chosen framing: {result.plan.chosen_framing_mode} — {result.plan.chosen_framing_why}"
            )
        if result.plan.outpaint_needed:
            st.warning("This framing requires outpainting — switching to background mode.")
    except CompilerError as exc:
        state.set("current_plan", plan)
        state.set("current_opgraph", None)
        state.set("change_requests_log", [])
        state.set("ui_phase", "plan_ready")
        state.set("plan_approved", False)
        state.set("error", str(exc))
    except Exception as exc:
        state.set("error", str(exc))
        state.set("ui_phase", "has_image")


def _do_revise_plan(change: str) -> None:
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.background.providers import default_provider_available
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.ops.validator import validate_crop_bounds
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError

    container = state.get("container")
    previous_plan = state.get("current_plan")
    mode = state.get("edit_mode") or "full"
    prefs = state.get("prefs")

    framing_val = state.get("framing_mode")
    fi = _build_framing_intent(framing_val) if framing_val else None
    genai_available = default_provider_available()
    try:
        # Inside the try so a misconfigured Character Focus backend surfaces as an
        # error banner instead of crashing the Streamlit script.
        detected_subject = _detect_subject_if_enabled(container)
        log_ = state.get("change_requests_log") or []
        log_.append(change)
        state.set("change_requests_log", log_)
        planner = Planner()
        plan = planner.revise(
            container, previous_plan, change, prefs, mode, fi, detected_subject, genai_available
        )

        max_retries = get_settings().max_crop_retries
        for _attempt in range(max_retries + 1):
            result = Compiler().compile(plan, mode, detected_subject=detected_subject)
            try:
                validate_crop_bounds(result.op_graph, container.width, container.height)
                break
            except ValueError as crop_err:
                if _attempt >= max_retries:
                    raise
                plan = planner.revise(
                    container,
                    plan,
                    str(crop_err),
                    prefs,
                    mode,
                    fi,
                    detected_subject,
                    genai_available,
                )

        state.set("current_plan", result.plan)
        state.set("current_opgraph", result.op_graph)
        state.set("ui_phase", "plan_ready")
        state.set("edited_container", None)
        state.set("genai_candidates", None)
        state.set("genai_override", None)
        state.set("change_request", "")
        state.set("error", None)
        from vlm_photo_editor.agents.edit_flow import _can_auto_approve

        _mode = AcceptMode(state.get("accept_mode") or AcceptMode.MANUAL.value)
        state.set("plan_approved", _can_auto_approve(result.op_graph, _mode))
    except CompilerError as exc:
        state.set("current_plan", plan)
        state.set("current_opgraph", None)
        state.set("ui_phase", "plan_ready")
        state.set("edited_container", None)
        state.set("genai_candidates", None)
        state.set("genai_override", None)
        state.set("change_request", "")
        state.set("plan_approved", False)
        state.set("error", str(exc))
    except Exception as exc:
        state.set("error", str(exc))
        state.set("change_request", "")


def _do_execute() -> None:
    from vlm_photo_editor.ops.executor import Executor
    from vlm_photo_editor.pipeline.job_queue import run_job
    from vlm_photo_editor.schema.ops import OpGraph

    container = state.get("container")
    op_graph: OpGraph = state.get("current_opgraph")
    bbox_raw = state.get("bbox")

    from vlm_photo_editor.ops.constants import INPAINT_OPS as _INPAINT_OPS
    from vlm_photo_editor.schema.ops import Backend as _Backend
    from vlm_photo_editor.schema.ops import OpName as _OpName

    needs_bbox = any(
        op.bbox is None
        and (
            (op.backend == _Backend.OPENCV and op.op_name in _INPAINT_OPS)
            or op.op_name == _OpName.FILL_MASK
            or op.params.get("invert") is True
        )
        for op in op_graph.ops
    )
    if needs_bbox and not (bbox_raw and bbox_raw.get("width", 0) > 0):
        state.set(
            "error",
            "This plan requires a region selection (OpenCV inpaint, fill_mask, or a mask "
            "step with no detected subject). Expand 'Region Selection (BBox)' and draw a "
            "rectangle before applying.",
        )
        return

    # Inject bbox into region-targeted ops if one was drawn.
    # bbox_raw stores normalized coords [0, 1]; scale to image pixels here.
    if bbox_raw and bbox_raw.get("width", 0) > 0 and bbox_raw.get("height", 0) > 0:
        img_w, img_h = container.width, container.height
        bbox = BoundingBox(
            x=int(bbox_raw["x"] * img_w),
            y=int(bbox_raw["y"] * img_h),
            width=max(1, int(bbox_raw["width"] * img_w)),
            height=max(1, int(bbox_raw["height"] * img_h)),
        )

        _REGION_OPS = {_OpName.BACKGROUND_REPLACE, _OpName.REGION_EDIT, _OpName.FILL_MASK}
        patched_ops = []
        for op in op_graph.ops:
            if op.bbox is None and op.params.get("invert") is True:
                # mask fallback (no detected subject): the drawn box stands in for the
                # subject bbox — the op still applies OUTSIDE it, so invert stays True.
                op = op.model_copy(update={"bbox": bbox})
            elif op.op_name in _REGION_OPS:
                op = op.model_copy(update={"bbox": bbox, "params": {**op.params, "invert": False}})
            patched_ops.append(op)
        op_graph = op_graph.model_copy(update={"ops": patched_ops})

    # Candidate override (BG-U2): replay the cached candidates for that step rather
    # than paying for a second generation.
    genai_selection = None
    override = state.get("genai_override")
    cached = state.get("genai_candidates")
    if override and cached:
        from vlm_photo_editor.background.quality import GenAISelection

        genai_selection = {
            step_id: GenAISelection(
                candidates=[sc.candidate for sc in cached[step_id]],
                override_index=idx,
            )
            for step_id, idx in override.items()
            if step_id in cached
        }

    try:
        _exec_progress = st.progress(0.0, text="Applying edits…")
        executor = Executor()
        result = run_job(
            executor.apply,
            container,
            op_graph,
            genai_selection,
            on_progress=lambda p: _exec_progress.progress(p, text="Applying edits…"),
        )
        state.set("edited_container", result.container)
        if result.genai_candidates:
            state.set("genai_candidates", result.genai_candidates)
        state.set("ui_phase", "done")
        state.set("error", None)
        state.log_intent(
            "execute",
            {
                "ops": len(op_graph.ops),
                "steps": [{"op": op.op_name.value, "params": op.params} for op in op_graph.ops],
            },
        )
        from vlm_photo_editor.schema.prefs import EditDelta

        ds = DeltaStore()
        ds.append(
            EditDelta(
                intent=state.get("intent") or "",
                mode=state.get("edit_mode") or "full",
                change_requests=state.get("change_requests_log") or [],
                accepted_ops=[op.op_name.value for op in op_graph.ops],
            )
        )
        if len(ds.list()) >= AGGREGATE_AFTER:
            state.set("run_aggregation", True)
    except Exception as exc:
        state.set("error", str(exc))


def _do_critic_check() -> bool:
    from vlm_photo_editor.agents.critic import Critic

    container = state.get("container")
    edited = state.get("edited_container")
    intent = state.get("intent") or ""
    verdict = Critic().verify(container.pixels, edited.pixels, intent)
    if verdict.passed:
        if verdict.uncertain:
            state.set("error", f"Critic check inconclusive: {verdict.reason}")
        return True
    state.set("error", f"Critic: {verdict.reason}")
    state.set("ui_phase", "plan_ready")
    state.set("edited_container", None)
    state.set("genai_candidates", None)
    state.set("genai_override", None)
    return False


def _do_aggregate() -> None:
    from vlm_photo_editor.agents.aggregator import Aggregator

    ds = DeltaStore()
    candidates = Aggregator().aggregate(ds.list())
    if candidates:
        ps = PreferenceStore()
        ps.add_learned(candidates)
        state.set("prefs", ps.load())
        ds.clear()
        st.info(f"{len(candidates)} new preference candidate(s) ready for review.")


def _render_batch_panel(files: list) -> None:
    import anyio

    from vlm_photo_editor.pipeline.batch import run_batch
    from vlm_photo_editor.schema.batch import BatchImageRecord

    st.subheader(f"Batch Processing — {len(files)} images")

    intent = st.text_area(
        "What would you like to do with these images?",
        height=80,
        key="batch_intent_input",
    )
    state.set("intent", intent)

    _edit_mode = state.get("edit_mode") or "full"
    col_full, col_bg, col_frame = st.columns(3)
    with col_full:
        if st.button(
            "Full Edit",
            use_container_width=True,
            type="primary" if _edit_mode == "full" else "secondary",
            key="batch_mode_btn_full",
        ):
            state.set("edit_mode", "full")
            st.rerun()
    with col_bg:
        if st.button(
            "Background",
            use_container_width=True,
            type="primary" if _edit_mode == "background" else "secondary",
            key="batch_mode_btn_bg",
        ):
            state.set("edit_mode", "background")
            st.rerun()
    with col_frame:
        if st.button(
            "Reframe Only",
            use_container_width=True,
            type="primary" if _edit_mode == "frame" else "secondary",
            key="batch_mode_btn_frame",
        ):
            state.set("edit_mode", "frame")
            st.rerun()

    records: list[BatchImageRecord] | None = state.get("batch_records")

    # Handle retry for a single image
    retry_id = state.get("batch_retry_id")
    if retry_id and records:
        record = next((r for r in records if r.image_id == retry_id), None)
        if record:
            state.set("batch_retry_id", None)
            with st.spinner(f"Re-planning {record.filename}…"):
                anyio.run(
                    run_batch,
                    [record],
                    state.get("intent") or "",
                    state.get("prefs"),
                    state.get("edit_mode") or "full",
                    None,
                    AcceptMode(state.get("accept_mode") or AcceptMode.MANUAL.value),
                    3,
                    None,
                )
            st.rerun()

    if st.button(
        "Start Batch Processing",
        key="start_batch_btn",
        disabled=not intent,
        type="primary",
    ):
        with st.spinner("Loading images…"):
            new_records: list[BatchImageRecord] = []
            for f in files:
                container = _load_uploaded(f)
                new_records.append(
                    BatchImageRecord(
                        filename=f.name,
                        container=container,
                        detected_subject=_detect_subject_if_enabled(container),
                    )
                )
        state.set("batch_records", new_records)
        records = new_records

        completed: list[int] = [0]
        overall_bar = st.progress(0.0, text="Planning images…")

        def _on_image_done(image_id: str) -> None:
            completed[0] += 1
            overall_bar.progress(
                completed[0] / len(records),
                text=f"Planned {completed[0]}/{len(records)} images…",
            )

        accept_mode = AcceptMode(state.get("accept_mode") or AcceptMode.MANUAL.value)
        framing_val = state.get("framing_mode")
        fi = _build_framing_intent(framing_val) if framing_val else None

        anyio.run(
            run_batch,
            records,
            intent,
            state.get("prefs"),
            state.get("edit_mode") or "full",
            fi,
            accept_mode,
            3,
            _on_image_done,
        )
        overall_bar.progress(1.0, text="Done.")
        state.set("batch_records", records)
        st.rerun()

    if records:
        batch_review.render(records)


def _do_save() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.imageio.savers import save as _save
    from vlm_photo_editor.recipe.store import RecipeStore
    from vlm_photo_editor.schema.recipe import Recipe

    edited = state.get("edited_container")
    op_graph = state.get("current_opgraph")
    source = edited.source_path
    stem = Path(state.get("source_name") or source.name).stem
    output_format = state.get("output_format") or "same"
    settings = get_settings()

    _RAW_EXTS = {".nef", ".cr2", ".arw", ".dng", ".orf", ".rw2"}
    _FORMAT_EXT = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif", "webp": ".webp"}
    _FORMAT_PIL = {"jpeg": "JPEG", "png": "PNG", "tiff": "TIFF", "webp": "WEBP"}

    if output_format == "same":
        if source.suffix.lower() in _RAW_EXTS:
            dest_suffix, pil_fmt = ".tif", "TIFF"
        else:
            dest_suffix, pil_fmt = source.suffix, None
    else:
        dest_suffix = _FORMAT_EXT[output_format]
        pil_fmt = _FORMAT_PIL[output_format]

    out_dir = Path(settings.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{stem}_edited{dest_suffix}"
    try:
        saved = _save(edited, dest, fmt=pil_fmt)
        state.set("saved_path", str(saved))
        state.set("saved_bytes", saved.read_bytes())
        state.set("saved_name", saved.name)

        recipe = Recipe(source_path=stem + source.suffix, op_graph=op_graph)
        RecipeStore.save(recipe, directory=Path(settings.recipes_dir))

        state.log_intent("save", {"path": str(saved)})
        state.set("error", None)
    except Exception as exc:
        state.set("error", str(exc))


# ── Process pending backend actions (before rendering) ────────────────────────

# Read from widget key — Streamlit pre-populates it before the script runs,
# so this works even though upload.render() hasn't executed yet on this pass.
# upload_widget returns a list when accept_multiple_files=True.
_widget_val = st.session_state.get("upload_widget")
if isinstance(_widget_val, list):
    _files = _widget_val
    if _files:
        _idx = int(state.get("current_file_index") or 0)
        _idx = max(0, min(_idx, len(_files) - 1))
        uploaded_file = _files[_idx]
    else:
        uploaded_file = None
else:
    uploaded_file = _widget_val or state.get("uploaded_file")

_is_batch = isinstance(_widget_val, list) and len(_widget_val) > 1
state.set("batch_mode", _is_batch)
if uploaded_file is not None:
    state.set("uploaded_file", uploaded_file)

# Auto-load when new file uploaded or container missing.
# Use object identity to detect file replacement without widget reset.
if uploaded_file is not None and (
    state.get("container") is None
    or state.get("_loaded_file_id") != f"{uploaded_file.name}:{uploaded_file.size}"
):
    with st.spinner("Loading image…"):
        try:
            container = _load_uploaded(uploaded_file)
            state.set("_loaded_file_id", f"{uploaded_file.name}:{uploaded_file.size}")
            state.set("container", container)
            state.set("ui_phase", "has_image")
            state.set("edited_container", None)
            state.set("genai_candidates", None)
            state.set("genai_override", None)
            state.set("current_plan", None)
            state.set("current_opgraph", None)
            state.set("saved_path", None)
            state.set("plan_approved", False)
        except Exception as exc:
            state.set("error", str(exc))

# When upload widget resets (new file), reset container too.
if uploaded_file is None and state.get("container") is not None:
    state.set("container", None)
    state.set("edited_container", None)
    state.set("genai_candidates", None)
    state.set("genai_override", None)
    state.set("current_plan", None)
    state.set("current_opgraph", None)
    state.set("ui_phase", "idle")
    state.set("saved_path", None)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("VLM Photo Editor")
st.caption("Propose → Approve → Apply. Originals are never altered.")

# ── Main layout ───────────────────────────────────────────────────────────────
sidebar_col, main_col = st.columns([1, 2])

with sidebar_col:
    upload.render()
    st.divider()

    st.subheader("Accept Mode")
    _ACCEPT_LABELS = {
        "manual": "Manual",
        "auto_low": "Auto-Accept Low Risk",
        "auto_medium": "Auto-Accept Medium Risk",
        "full_auto": "Full Auto",
    }
    accept_mode = st.radio(
        "Approval flow:",
        options=[m.value for m in AcceptMode],
        format_func=_ACCEPT_LABELS.get,
        horizontal=False,
        key="accept_mode_radio",
    )
    state.set("accept_mode", accept_mode)

    st.divider()

    st.subheader("Critic")
    critic_enabled = st.checkbox(
        "Enable Critic (auto quality check)",
        value=bool(state.get("critic_enabled")),
        key="critic_enabled_checkbox",
    )
    state.set("critic_enabled", critic_enabled)

    st.divider()

    st.subheader("Output Format")
    _FMT_OPTIONS = ["same", "jpeg", "png", "tiff", "webp"]
    _FMT_LABELS = {
        "same": "Same as input",
        "jpeg": "JPEG",
        "png": "PNG",
        "tiff": "TIFF",
        "webp": "WebP",
    }
    output_format = st.selectbox(
        "Format:",
        options=_FMT_OPTIONS,
        format_func=_FMT_LABELS.get,
        key="output_format_select",
    )
    state.set("output_format", output_format)

    st.divider()
    settings_component.render()

with main_col:
    if state.get("batch_mode") and isinstance(_widget_val, list) and len(_widget_val) > 1:
        _render_batch_panel(_widget_val)
    else:
        # ── Single-image flow ──────────────────────────────────────────────────

        # Error banner
        if state.get("error"):
            st.error(state.get("error"))

        ui_phase = state.get("ui_phase") or "idle"

        # Before/after preview — shown first so intent area appears beneath the image
        container = state.get("container")
        edited = state.get("edited_container")
        preview.render(
            before=container.pixels if container else None,
            after=edited.pixels if edited else None,
        )

        # Intent input + plan generation (below preview)
        if ui_phase in ("has_image", "plan_ready", "done"):
            st.divider()

            # Quick-mode prefill buttons (U2): set edit_mode and populate intent from template.
            from vlm_photo_editor import templates as prompt_templates

            _edit_mode = state.get("edit_mode") or "full"
            col_full, col_bg, col_frame = st.columns(3)
            with col_full:
                if st.button(
                    "Full Edit",
                    use_container_width=True,
                    type="primary" if _edit_mode == "full" else "secondary",
                    key="mode_btn_full",
                ):
                    st.session_state["intent_input"] = prompt_templates.load("full_edit")
                    state.set("edit_mode", "full")
                    state.set("_last_auto_gen_key", "")
                    state.log_intent("mode_change", {"mode": "full"})
                    st.rerun()
            with col_bg:
                if st.button(
                    "Background",
                    use_container_width=True,
                    type="primary" if _edit_mode == "background" else "secondary",
                    key="mode_btn_bg",
                ):
                    st.session_state["intent_input"] = prompt_templates.load("background")
                    state.set("edit_mode", "background")
                    state.set("_last_auto_gen_key", "")
                    state.log_intent("mode_change", {"mode": "background"})
                    st.rerun()
            with col_frame:
                if st.button(
                    "Reframe Only",
                    use_container_width=True,
                    type="primary" if _edit_mode == "frame" else "secondary",
                    key="mode_btn_frame",
                ):
                    st.session_state["intent_input"] = prompt_templates.load("frame")
                    state.set("edit_mode", "frame")
                    state.set("_last_auto_gen_key", "")
                    state.log_intent("mode_change", {"mode": "frame"})
                    st.rerun()

            _edit_mode = state.get("edit_mode") or "full"

            # Framing mode selector — always visible
            _framing_mode = state.get("framing_mode") or FramingMode.RULE_OF_THIRDS.value
            _framing_opts = [m.value for m in FramingMode]
            _framing_idx = (
                _framing_opts.index(_framing_mode) if _framing_mode in _framing_opts else 0
            )
            _framing_mode = st.selectbox(
                "Composition:",
                options=_framing_opts,
                index=_framing_idx,
                key="framing_mode_select",
            )
            state.set("framing_mode", _framing_mode)

            if _framing_mode == FramingMode.RECOMMEND_BEST.value:
                st.text_input("Framing guidance (optional)", key="framing_hint")

            # Character Focus selector — local subject detection, off by default.
            # Only offer backends with a resolvable model path; the rest would raise
            # a misconfiguration error the moment a plan is generated.
            from vlm_photo_editor.detection import ready_backends

            _cf_opts = ["off"] + ready_backends()
            _cf_current = state.get("character_focus") or "off"
            if _cf_current not in _cf_opts:
                _cf_current = "off"
            _character_focus = st.selectbox(
                "Character Focus:",
                options=_cf_opts,
                index=_cf_opts.index(_cf_current),
                key="character_focus_select",
            )
            state.set("character_focus", _character_focus)

            # Auto-generate when Reframe Only + non-Custom composition (U3).
            # Any change in framing_mode triggers a new plan without a button press.
            _is_frame_auto = _edit_mode == "frame" and _framing_mode != FramingMode.CUSTOM.value
            _auto_gen_key = f"frame:{_framing_mode}" if _is_frame_auto else ""
            if _is_frame_auto and state.get("_last_auto_gen_key") != _auto_gen_key:
                state.set("_last_auto_gen_key", _auto_gen_key)
                with st.spinner(f"Generating plan for {_framing_mode}…"):
                    _do_generate_plan()
                st.rerun()

            # Intent text area + Generate button — hidden when frame auto-generates (U3)
            if not _is_frame_auto:
                intent = st.text_area(
                    "What would you like to do with this image?",
                    height=120,
                    key="intent_input",
                )
                state.set("intent", intent)

                generate_label = "Generate Plan" if ui_phase == "has_image" else "Regenerate Plan"
                if st.button(generate_label, key="generate_plan_btn", disabled=not intent):
                    with st.spinner("Generating plan…"):
                        _do_generate_plan()
                    st.rerun()

        st.divider()

        # BBox canvas — show when image is loaded
        if ui_phase in ("has_image", "plan_ready", "done"):
            canvas.render(background_pixels=container.pixels if container else None)
            st.divider()

        # Plan view + accept/change flow
        current_plan = state.get("current_plan")
        current_opgraph = state.get("current_opgraph")

        if ui_phase in ("plan_ready", "done") and current_plan is not None:
            plan_view.render(current_plan, current_opgraph, executed=(ui_phase == "done"))

            # Handle Accept Plan
            if state.get("plan_approved") and ui_phase != "done":
                with st.spinner("Executing plan…"):
                    _do_execute()
                state.set("plan_approved", False)
                if state.get("ui_phase") == "done" and state.get("critic_enabled"):
                    with st.spinner("Critic verifying…"):
                        if not _do_critic_check():
                            st.rerun()
                st.rerun()

            # Handle Change Request
            change = state.get("change_request") or ""
            if change:
                with st.spinner("Revising plan…"):
                    _do_revise_plan(change)
                st.rerun()

            # genAI candidate override (BG-U2)
            if ui_phase == "done" and state.get("genai_candidates"):
                st.divider()
                picked = candidate_picker.render(
                    state.get("genai_candidates"),
                    state.get("genai_override"),
                )
                if picked is not None:
                    step_id, idx = picked
                    override = dict(state.get("genai_override") or {})
                    override[step_id] = idx
                    state.set("genai_override", override)
                    state.log_intent("candidate_override", {"step_id": step_id, "index": idx})
                    with st.spinner("Applying candidate…"):
                        _do_execute()
                    st.rerun()

        # Handle aggregation (runs after execution or on manual trigger from prefs panel)
        if state.get("run_aggregation"):
            with st.spinner("Summarizing preferences…"):
                _do_aggregate()
            state.set("run_aggregation", False)
            st.rerun()

        elif ui_phase == "idle":
            st.info("Upload an image to begin.")

        st.divider()
        prefs = state.get("prefs") or PreferenceStore().load()
        state.set("prefs", prefs)
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

    saved_bytes = state.get("saved_bytes")
    if saved_bytes:
        st.download_button(
            "Download edited file",
            data=saved_bytes,
            file_name=state.get("saved_name") or "edited",
            key="save_download",
        )

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
