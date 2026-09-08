"""Batch review UI component — rendered after run_batch() completes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import streamlit as st

from vlm_photo_editor.app import state
from vlm_photo_editor.app.components import preview
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


def render(records: list[BatchImageRecord]) -> None:
    _render_summary(records)

    review_list = [r for r in records if r.status == ImageStatus.NEEDS_REVIEW]
    if review_list:
        _render_review_panel(review_list, records)

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


def _render_review_panel(
    review_list: list[BatchImageRecord], all_records: list[BatchImageRecord]
) -> None:
    st.subheader("Review Queue")

    idx = int(state.get("batch_review_index") or 0)
    idx = max(0, min(idx, len(review_list) - 1))

    # Navigation
    nav_left, nav_center, nav_right = st.columns([1, 4, 1])
    with nav_left:
        if st.button("←", key="batch_nav_prev", disabled=idx == 0):
            state.set("batch_review_index", idx - 1)
            st.rerun()
    with nav_center:
        st.caption(f"Image {idx + 1} of {len(review_list)}: **{review_list[idx].filename}**")
    with nav_right:
        if st.button("→", key="batch_nav_next", disabled=idx == len(review_list) - 1):
            state.set("batch_review_index", idx + 1)
            st.rerun()

    record = review_list[idx]

    # Before preview (no after yet — not executed)
    preview.render(
        before=record.container.pixels if record.container else None,
        after=None,
    )

    # Plan steps
    if record.plan and record.plan.steps:
        with st.expander("Plan steps", expanded=True):
            for step in record.plan.steps:
                st.markdown(f"**{step.step_id}** — {step.title}")
                if step.why:
                    st.caption(step.why)

    # Action buttons
    col_acc, col_rej = st.columns(2)
    with col_acc:
        if st.button("Accept", key=f"batch_accept_{record.image_id}", type="primary"):
            _execute_and_accept(record)
            state.set("batch_review_index", max(0, idx - 1))
            st.rerun()
    with col_rej:
        if st.button("Reject", key=f"batch_reject_{record.image_id}"):
            record.status = ImageStatus.REJECTED
            state.set("batch_review_index", max(0, idx - 1))
            st.rerun()

    # Re-plan via chat
    feedback = st.text_input("Request changes (re-plan):", key=f"batch_replan_{record.image_id}")
    if st.button("Re-plan", key=f"batch_replan_btn_{record.image_id}", disabled=not feedback):
        _replan_record(record, feedback)
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
            revised = Planner().revise(
                record.container,
                record.plan,
                feedback,
                prefs,
                mode,
                None,
                detected_subject=record.detected_subject,
                genai_available=genai_available,
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
        anyio.run(run_batch, [record], intent, prefs, mode, None, accept_mode, 3, None)


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

    # Also show auto-executed images read-only with revert option
    for record in [r for r in records if r.status == ImageStatus.AUTO_EXECUTED]:
        with st.expander(f"Auto-executed: {record.filename}", expanded=False):
            preview.render(
                before=record.container.pixels if record.container else None,
                after=record.edited_container.pixels if record.edited_container else None,
            )
            if st.button("Revert", key=f"batch_revert_{record.image_id}"):
                record.edited_container = None
                record.status = ImageStatus.NEEDS_REVIEW
                st.rerun()


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
