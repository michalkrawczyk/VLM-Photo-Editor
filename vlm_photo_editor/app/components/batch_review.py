"""Batch review UI component — rendered after run_batch() completes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import streamlit as st
from PIL import Image, ImageOps

from vlm_photo_editor.app import state
from vlm_photo_editor.app.components import preview
from vlm_photo_editor.app.components.framing import current_framing_intent
from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.imageio.savers import save as _save
from vlm_photo_editor.pipeline.batch import _safe_error
from vlm_photo_editor.schema.batch import BatchImageRecord, ImageStatus
from vlm_photo_editor.schema.ops import AcceptMode

if TYPE_CHECKING:
    pass

_FORMAT_EXT: dict[str, str] = {
    "jpeg": ".jpg",
    "png": ".png",
    "tiff": ".tif",
    "webp": ".webp",
}
_FORMAT_PIL: dict[str, str] = {
    "jpeg": "JPEG",
    "png": "PNG",
    "tiff": "TIFF",
    "webp": "WEBP",
}
_RAW_EXTS = {".nef", ".cr2", ".arw", ".dng", ".orf", ".rw2"}
_PREVIEW_MAX_EDGE = 1600
_PREVIEW_CACHE_KEY = "_batch_preview_cache"
_PREVIEW_CACHE_SIZE = 8


def render(records: list[BatchImageRecord]) -> None:
    _render_summary(records)
    if records:
        _render_details(records)
    _render_save_all(records)
    _render_needs_attention(records)


def _render_summary(records: list[BatchImageRecord]) -> None:
    counts = {s: 0 for s in ImageStatus}
    for r in records:
        counts[r.status] += 1

    auto = counts[ImageStatus.AUTO_EXECUTED]
    accepted = counts[ImageStatus.ACCEPTED]
    review = counts[ImageStatus.NEEDS_REVIEW]
    rejected = counts[ImageStatus.REJECTED]
    failed = counts[ImageStatus.FAILED]

    st.info(
        f"{auto} auto-executed · {accepted} accepted · "
        f"{review} need review · {rejected} rejected · {failed} failed"
    )


def _clamp_index(idx: int, n: int) -> int:
    return max(0, min(idx, n - 1))


def _next_review_index(records: list[BatchImageRecord], idx: int) -> int:
    """Index of the next NEEDS_REVIEW record after ``idx`` (wrapping); ``idx`` if none."""
    n = len(records)
    for step in range(1, n + 1):
        j = (idx + step) % n
        if records[j].status == ImageStatus.NEEDS_REVIEW:
            return j
    return idx


def _after_pixels(record: BatchImageRecord):
    return record.edited_container.pixels if record.edited_container is not None else None


def _render_details(records: list[BatchImageRecord]) -> None:
    """Status, plan and review actions for the image shown in the top preview."""
    st.subheader("Batch Results")
    idx = _clamp_index(int(state.get("batch_view_index") or 0), len(records))
    record = records[idx]
    st.caption(
        f"**{record.filename}** — {record.status.value.replace('_', ' ')} "
        "(use ◀ ▶ in the preview above to switch image)"
    )
    if record.status == ImageStatus.NEEDS_REVIEW:
        st.caption("Not executed yet — the After image appears once you accept.")
    if record.error:
        st.error(record.error)

    _render_plan_details(record)
    _render_record_actions(records, idx, record)


def _original_pixels(file):
    """Display-size pixels of an uploaded file (None for RAW), cached per ``name:size``."""
    if Path(file.name).suffix.lower() in _RAW_EXTS:
        return None
    key = f"{file.name}:{file.size}"
    cache = st.session_state.setdefault(_PREVIEW_CACHE_KEY, {})
    if key in cache:
        return cache[key]
    try:
        with Image.open(io.BytesIO(file.getvalue())) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((_PREVIEW_MAX_EDGE, _PREVIEW_MAX_EDGE))
            pixels = np.asarray(im)
    except Exception:
        return None
    cache[key] = pixels
    while len(cache) > _PREVIEW_CACHE_SIZE:
        cache.pop(next(iter(cache)))  # dicts keep insertion order: drop the oldest
    return pixels


def plan_preview_blocked_reason(op_graph) -> str | None:
    """Why the approved plan must not be previewed on a single image, or None if it may."""
    from vlm_photo_editor.ops.constants import INPAINT_OPS
    from vlm_photo_editor.schema.ops import Backend, OpName

    if op_graph is None:
        return "The plan has not compiled."
    for op in op_graph.ops:
        if op.backend in (Backend.GENAI, Backend.PHOTOSHOP):
            return (
                "The plan uses generative/Photoshop steps; the result appears after Apply to all."
            )
        if op.bbox is None and (
            (op.backend == Backend.OPENCV and op.op_name in INPAINT_OPS)
            or op.op_name == OpName.FILL_MASK
            or op.params.get("invert") is True
        ):
            return "The plan needs a region selection, which batch mode does not offer."
    return None


def plan_preview_key(plan, file_key: str) -> str:
    """Identity of a plan-preview result: changes whenever the plan content or image changes."""
    return f"{hash(plan.model_dump_json())}:{file_key}"


def render_preview(files: list, records: list[BatchImageRecord] | None) -> None:
    """Big Before/After preview with prev/next, like single mode.

    Before a run it browses the uploaded originals; afterwards the processed records.
    """
    items = records or files
    if not items:
        return
    idx = _clamp_index(int(state.get("batch_view_index") or 0), len(items))

    nav_left, nav_center, nav_right = st.columns([1, 4, 1])
    with nav_left:
        if st.button("◀", key="batch_nav_prev", disabled=idx == 0):
            state.set("batch_view_index", idx - 1)
            st.rerun()
    with nav_right:
        if st.button("▶", key="batch_nav_next", disabled=idx == len(items) - 1):
            state.set("batch_view_index", idx + 1)
            st.rerun()

    note = ""
    if records:
        record = records[idx]
        name = record.filename
        note = record.status.value.replace("_", " ")
        before = record.container.pixels if record.container else None
        after = _after_pixels(record)
    else:
        file = items[idx]
        name = file.name
        file_key = f"{file.name}:{file.size}"
        before = _original_pixels(file)
        after = None
        if state.get("current_plan") is not None and state.get("_loaded_file_id") == file_key:
            note = "plan image"
            pp = state.get("batch_plan_preview")
            if pp and pp["key"] == plan_preview_key(state.get("current_plan"), file_key):
                after = pp["container"].pixels
        if before is None:
            note = (note + " · " if note else "") + "RAW preview available after processing"
    with nav_center:
        st.caption(f"Image {idx + 1} of {len(items)}: **{name}**" + (f" — {note}" if note else ""))

    preview.render(before=before, after=after)


def _render_plan_details(record: BatchImageRecord) -> None:
    if record.plan is None:
        return
    ops_by_step: dict[str, list] = {}
    if record.op_graph is not None:
        for op in record.op_graph.ops:
            ops_by_step.setdefault(op.step_id, []).append(op)

    with st.expander("Plan", expanded=True):
        if record.plan.diagnosis:
            st.markdown(f"**Diagnosis:** {record.plan.diagnosis}")
        if not record.plan.steps:
            st.caption("No edits planned.")
        for step in record.plan.steps:
            st.markdown(f"**{step.index}. {step.title}**")
            if step.why:
                st.caption(step.why)
            for op in ops_by_step.get(step.step_id, []):
                st.code(
                    f"{op.op_name.value}({op.params}) via {op.backend.value}"
                    f" [{op.risk_tier.value} risk]"
                )
        for g in record.genai_ops or []:
            seed = "none" if g.seed is None else g.seed
            st.caption(f"genAI: model={g.model} seed={seed} prompt={g.prompt!r}")


def _render_record_actions(records: list[BatchImageRecord], idx: int, record: BatchImageRecord):
    if record.status == ImageStatus.NEEDS_REVIEW:
        col_acc, col_rej = st.columns(2)
        with col_acc:
            if st.button("Accept", key=f"batch_accept_{record.image_id}", type="primary"):
                _execute_and_accept(record)
                if record.status == ImageStatus.ACCEPTED:
                    state.set("batch_view_index", _next_review_index(records, idx))
                st.rerun()
        with col_rej:
            if st.button("Reject", key=f"batch_reject_{record.image_id}"):
                record.status = ImageStatus.REJECTED
                state.set("batch_view_index", _next_review_index(records, idx))
                st.rerun()

        feedback = st.text_input(
            "Request changes (re-plan):", key=f"batch_replan_{record.image_id}"
        )
        if st.button("Re-plan", key=f"batch_replan_btn_{record.image_id}", disabled=not feedback):
            _replan_record(record, feedback)
            st.rerun()
    elif record.status == ImageStatus.AUTO_EXECUTED:
        if st.button("Revert", key=f"batch_revert_{record.image_id}"):
            record.edited_container = None
            record.status = ImageStatus.NEEDS_REVIEW
            st.rerun()


def _execute_and_accept(record: BatchImageRecord) -> None:
    from vlm_photo_editor.ops.executor import Executor
    from vlm_photo_editor.pipeline.job_queue import run_job

    try:
        result = run_job(Executor().apply, record.container, record.op_graph)
        record.edited_container = result.container
        record.genai_ops = result.genai_ops
        record.status = ImageStatus.ACCEPTED
    except Exception as exc:
        record.status = ImageStatus.FAILED
        record.error = _safe_error(exc)
        st.error(f"Execution failed: {record.error}")


def _replan_record(record: BatchImageRecord, feedback: str) -> None:
    import anyio

    from vlm_photo_editor.pipeline.batch import run_batch

    intent = record.intent or state.get("intent") or ""
    prefs = state.get("prefs")
    mode = state.get("edit_mode") or "full"
    accept_mode = AcceptMode(state.get("accept_mode") or AcceptMode.MANUAL.value)

    # Re-use Planner.revise if we have a prior plan; otherwise re-plan from scratch.
    if record.plan is not None:
        from vlm_photo_editor.agents.planner import Planner
        from vlm_photo_editor.background.providers import default_provider_available
        from vlm_photo_editor.planner.compiler import Compiler

        try:
            genai_available = default_provider_available()
            image_report = None
            if get_settings().image_report_enabled:
                from vlm_photo_editor.analysis import compute_report

                image_report = compute_report(record.container)
            revised = Planner().revise(
                record.container,
                record.plan,
                feedback,
                prefs,
                mode,
                current_framing_intent(),
                detected_subject=record.detected_subject,
                genai_available=genai_available,
                image_report=image_report,
                original_intent=record.intent or state.get("intent") or None,
            )
            result = Compiler().compile(revised, mode, detected_subject=record.detected_subject)
            record.plan = result.plan
            record.op_graph = result.op_graph
            record.status = ImageStatus.NEEDS_REVIEW
            record.error = None
        except Exception as exc:
            record.status = ImageStatus.FAILED
            record.error = _safe_error(exc)
            st.error(f"Re-plan failed: {record.error}")
    else:
        record.status = ImageStatus.PENDING
        record.error = None
        anyio.run(
            run_batch,
            [record],
            intent,
            prefs,
            mode,
            current_framing_intent(),
            accept_mode,
            3,
            None,
        )


def _render_save_all(records: list[BatchImageRecord]) -> None:
    saveable = [r for r in records if r.status in (ImageStatus.ACCEPTED, ImageStatus.AUTO_EXECUTED)]
    if not saveable:
        return

    st.divider()
    output_format = state.get("output_format") or "same"

    settings = get_settings()
    out_dir = Path(settings.output_dir) / "batch"
    st.caption(f"Output directory: `{out_dir}`")

    if st.button(f"Save All Accepted ({len(saveable)} images)", key="batch_save_all"):
        out_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = _save_all_accepted(
            saveable, output_format, out_dir, Path(settings.recipes_dir) / "batch"
        )
        if saved_paths:
            st.success(f"Saved {len(saved_paths)} files to {out_dir}.")
            _offer_zip(saved_paths)


def _save_all_accepted(
    records: list[BatchImageRecord],
    output_format: str,
    out_dir: Path,
    recipes_dir: Path,
) -> list[Path]:
    from vlm_photo_editor.recipe.store import RecipeStore
    from vlm_photo_editor.schema.recipe import Recipe

    saved: list[Path] = []
    for record in records:
        if record.status not in (ImageStatus.ACCEPTED, ImageStatus.AUTO_EXECUTED):
            continue
        if record.edited_container is None:
            continue
        stem = Path(record.filename).stem
        src_suffix = Path(record.filename).suffix.lower()

        if output_format == "same":
            if src_suffix in _RAW_EXTS:
                dest_suffix, pil_fmt = ".tif", "TIFF"
            else:
                dest_suffix, pil_fmt = src_suffix, None
        else:
            dest_suffix = _FORMAT_EXT[output_format]
            pil_fmt = _FORMAT_PIL[output_format]

        dest = out_dir / f"{stem}_edited{dest_suffix}"
        try:
            path = _save(record.edited_container, dest, fmt=pil_fmt)
            saved.append(path)
            if record.op_graph is not None:
                recipe = Recipe(
                    source_path=record.filename,
                    op_graph=record.op_graph,
                    genai_ops=list(record.genai_ops or []),
                )
                RecipeStore.save(recipe, directory=recipes_dir)
        except Exception as exc:
            st.error(f"Save failed for {record.filename}: {_safe_error(exc)}")

    return saved


def _offer_zip(paths: list[Path]) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    buf.seek(0)
    st.download_button(
        "Download ZIP",
        data=buf,
        file_name="batch_edited.zip",
        mime="application/zip",
        key="batch_zip_download",
    )


def _render_needs_attention(records: list[BatchImageRecord]) -> None:
    failed = [r for r in records if r.status == ImageStatus.FAILED]
    if not failed:
        return

    with st.expander(f"Needs Attention ({len(failed)})", expanded=True):
        for record in failed:
            st.error(f"**{record.filename}**: {record.error or 'unknown error'}")
            if st.button("Retry", key=f"batch_retry_{record.image_id}"):
                record.status = ImageStatus.PENDING
                record.error = None
                record.retry_count = 0
                state.set("batch_retry_id", record.image_id)
                st.rerun()
