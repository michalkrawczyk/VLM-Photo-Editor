"""File upload widget. Contract: sets state['uploaded_file'] on upload."""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state


def render() -> None:
    st.subheader("Upload Image")
    file = st.file_uploader(
        "Choose an image (JPG, PNG, NEF, CR2, ARW, DNG)",
        type=["jpg", "jpeg", "png", "nef", "cr2", "arw", "dng"],
        key="upload_widget",
    )
    if file is not None:
        state.set("uploaded_file", file)
        state.log_intent("upload", {"filename": file.name, "size": file.size})
        st.success(f"Loaded: {file.name} ({file.size:,} bytes)")
    elif state.get("uploaded_file") is None:
        st.info("No image loaded. Upload to begin.")
