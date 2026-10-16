"""File upload widget. Contract: sets state['uploaded_file'] on upload."""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state


def render() -> None:
    st.subheader("Upload Image")
    files = st.file_uploader(
        "Choose images (JPG, PNG, NEF, CR2, ARW, DNG)",
        type=["jpg", "jpeg", "png", "nef", "cr2", "arw", "dng"],
        accept_multiple_files=True,
        key="upload_widget",
    )
    if files:
        # Reset index when file set changes.
        prev_ids = {f"{f.name}:{f.size}" for f in (state.get("uploaded_files") or [])}
        curr_ids = {f"{f.name}:{f.size}" for f in files}
        if prev_ids != curr_ids:
            state.set("uploaded_files", files)
            state.set("current_file_index", 0)
            # Results of a previous batch belong to the old file set.
            state.set("batch_records", None)
            state.set("batch_view_index", 0)

        idx = int(state.get("current_file_index") or 0)
        idx = max(0, min(idx, len(files) - 1))

        if len(files) > 1:
            col_prev, col_sel, col_next = st.columns([1, 4, 1])
            with col_prev:
                if st.button("◀", key="prev_img_btn", disabled=(idx == 0)):
                    state.set("current_file_index", idx - 1)
                    st.rerun()
            with col_sel:
                options = [f.name for f in files]
                sel = st.selectbox(
                    "Active image:",
                    options,
                    index=idx,
                    key="file_nav_select",
                    label_visibility="collapsed",
                )
                new_idx = options.index(sel)
                if new_idx != idx:
                    state.set("current_file_index", new_idx)
                    st.rerun()
            with col_next:
                if st.button("▶", key="next_img_btn", disabled=(idx == len(files) - 1)):
                    state.set("current_file_index", idx + 1)
                    st.rerun()

        current_file = files[idx]
        state.set("uploaded_file", current_file)
        container = state.get("container")
        dims = f"{container.width}×{container.height}" if container is not None else None
        label = f"Loaded: {current_file.name} ({current_file.size:,} bytes)"
        if dims:
            label += f" — {dims}"
        if len(files) > 1:
            label += f" ({idx + 1}/{len(files)})"
        st.success(label)
    elif state.get("uploaded_file") is None:
        st.info("No image loaded. Upload to begin.")
