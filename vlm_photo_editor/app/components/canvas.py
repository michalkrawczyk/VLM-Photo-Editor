"""BBox-draw canvas for region selection.

Contract:
  - On draw, sets state['bbox'] = {x, y, width, height} as normalized coords in [0, 1].
  - Caller must scale to image pixels: x*img_w, y*img_h, width*img_w, height*img_h.
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

_CANVAS_W = 600


def render(background_pixels=None) -> None:
    st.subheader("Region Selection (BBox)")

    if not _CANVAS_AVAILABLE:
        st.warning(
            "streamlit-drawable-canvas not installed. Run: pip install streamlit-drawable-canvas"
        )
        return

    import numpy as np

    bg_image = None
    canvas_h = 300

    if background_pixels is not None:
        from PIL import Image

        px = background_pixels
        if px.dtype != np.uint8:
            px = (px >> 8).astype(np.uint8)
        if px.ndim == 3 and px.shape[2] == 4:
            px = px[:, :, :3]
        img_h, img_w = px.shape[:2]
        canvas_h = max(100, int(_CANVAS_W * img_h / img_w))
        bg_image = Image.fromarray(px).resize((_CANVAS_W, canvas_h))

    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=2,
        stroke_color="#FF4444",
        background_image=bg_image,
        background_color="#2a2a2a" if bg_image is None else "",
        height=canvas_h,
        width=_CANVAS_W,
        drawing_mode="rect",
        key="bbox_canvas",
    )

    if canvas_result.json_data is not None:
        objects = canvas_result.json_data.get("objects", [])
        if objects:
            obj = objects[-1]
            raw_x = obj.get("left", 0)
            raw_y = obj.get("top", 0)
            raw_w = obj.get("width", 0)
            raw_h = obj.get("height", 0)
            if raw_w > 0 and raw_h > 0:
                bbox = {
                    "x": raw_x / _CANVAS_W,
                    "y": raw_y / canvas_h,
                    "width": raw_w / _CANVAS_W,
                    "height": raw_h / canvas_h,
                }
                state.set("bbox", bbox)
                state.log_intent("bbox_drawn", bbox)
                st.caption(
                    f"Region: {bbox['x']:.1%}–{bbox['x']+bbox['width']:.1%} × "
                    f"{bbox['y']:.1%}–{bbox['y']+bbox['height']:.1%}"
                )
