"""Before/after side-by-side preview. Contract: accepts PIL Images or None (shows placeholder)."""

from __future__ import annotations

import streamlit as st
from PIL import Image

_PLACEHOLDER_SIZE = (600, 400)
_PLACEHOLDER_COLOR = (40, 40, 40)


def _placeholder() -> Image.Image:
    return Image.new("RGB", _PLACEHOLDER_SIZE, color=_PLACEHOLDER_COLOR)


def render(before: Image.Image | None = None, after: Image.Image | None = None) -> None:
    st.subheader("Preview")
    col_b, col_a = st.columns(2)
    with col_b:
        st.caption("Before")
        st.image(before or _placeholder(), use_container_width=True)
    with col_a:
        st.caption("After [STUB — no processing yet]")
        st.image(after or _placeholder(), use_container_width=True)
