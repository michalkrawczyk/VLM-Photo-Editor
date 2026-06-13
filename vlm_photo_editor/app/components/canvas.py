"""BBox-draw canvas for region selection.

Contract:
  - On draw, sets state['bbox'] = {x, y, width, height} and logs intent.
  - Coordinates map directly to BoundingBox schema for Op.
  - Gracefully degrades if streamlit-drawable-canvas is not installed.
"""

from __future__ import annotations

import streamlit as st

from vlm_photo_editor.app import state

try:
    from streamlit_drawable_canvas import st_canvas

    _CANVAS_AVAILABLE = True
except ImportError:
    _CANVAS_AVAILABLE = False


def render() -> None:
    st.subheader("Region Selection (BBox) [STUB]")

    if not _CANVAS_AVAILABLE:
        st.warning(
            "streamlit-drawable-canvas not installed. " "Run: pip install streamlit-drawable-canvas"
        )
        return

    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=2,
        stroke_color="#FF4444",
        background_color="#2a2a2a",
        height=300,
        width=600,
        drawing_mode="rect",
        key="bbox_canvas",
    )

    if canvas_result.json_data is not None:
        objects = canvas_result.json_data.get("objects", [])
        if objects:
            obj = objects[-1]
            bbox = {
                "x": int(obj.get("left", 0)),
                "y": int(obj.get("top", 0)),
                "width": int(obj.get("width", 0)),
                "height": int(obj.get("height", 0)),
            }
            if bbox["width"] > 0 and bbox["height"] > 0:
                state.set("bbox", bbox)
                state.log_intent("bbox_drawn", bbox)
                st.caption(f"Selected region: {bbox}")
