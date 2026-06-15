"""Before/after side-by-side preview. Accepts numpy arrays, PIL Images, or None."""

from __future__ import annotations

from typing import Union

import numpy as np
import streamlit as st
from PIL import Image

_PLACEHOLDER_SIZE = (600, 400)
_PLACEHOLDER_COLOR = (40, 40, 40)

DisplayImage = Union[np.ndarray, Image.Image, None]


def _placeholder() -> Image.Image:
    return Image.new("RGB", _PLACEHOLDER_SIZE, color=_PLACEHOLDER_COLOR)


def _to_display(img: DisplayImage) -> Image.Image:
    if img is None:
        return _placeholder()
    if isinstance(img, np.ndarray):
        if img.dtype == np.uint16:
            img = (img >> 8).astype(np.uint8)
        return Image.fromarray(img.astype(np.uint8) if img.dtype != np.uint8 else img)
    return img


def render(before: DisplayImage = None, after: DisplayImage = None) -> None:
    st.subheader("Preview")
    col_b, col_a = st.columns(2)
    with col_b:
        st.caption("Before")
        st.image(_to_display(before), use_container_width=True)
    with col_a:
        after_label = "After" if after is not None else "After (pending execution)"
        st.caption(after_label)
        st.image(_to_display(after), use_container_width=True)
