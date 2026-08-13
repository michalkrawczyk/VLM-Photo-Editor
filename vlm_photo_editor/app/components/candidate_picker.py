"""genAI candidate picker. Shows every candidate the pipeline generated and scored,
so the user can override the automatic pick (BG-U2)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from .preview import _to_display

_THUMB_WIDTH = 220


def render(
    candidates: dict[str, list[Any]],
    selected: dict[str, int] | None = None,
) -> tuple[str, int] | None:
    """Render one thumbnail row per genAI step.

    Returns (step_id, index) when the user clicks a different candidate, else None.
    `candidates` maps step_id → list[ScoredCandidate], already sorted best-first.
    """
    if not candidates:
        return None

    selected = selected or {}
    clicked: tuple[str, int] | None = None

    st.subheader("Background candidates")
    st.caption("All candidates generated for this step. Lower seam score is a smoother blend.")

    for step_id, scored in candidates.items():
        if len(candidates) > 1:
            st.caption(f"Step {step_id}")
        current = selected.get(step_id, 0)
        cols = st.columns(len(scored))
        for idx, (col, sc) in enumerate(zip(cols, scored)):
            with col:
                st.image(_to_display(sc.composite.pixels), width=_THUMB_WIDTH)
                st.caption(f"seed {sc.candidate.genai_op.seed} · seam {sc.metric:.3f}")
                if idx == current:
                    st.button(
                        "In use",
                        key=f"cand_{step_id}_{idx}",
                        disabled=True,
                        use_container_width=True,
                    )
                elif st.button(
                    "Use this",
                    key=f"cand_{step_id}_{idx}",
                    use_container_width=True,
                ):
                    clicked = (step_id, idx)

    return clicked
