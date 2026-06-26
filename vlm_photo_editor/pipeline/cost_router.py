"""Lightweight cost router: classifies user intent as trivial or complex
before committing to a full VLM planning call.

Uses the cost_router registry role (default: LiquidAI/LFM2.5-1.2B-Instruct,
local, no API key). Fails open to "complex" so a model outage never blocks work.
"""

from __future__ import annotations

import logging
from typing import Literal

_log = logging.getLogger(__name__)


def classify_intent(mode: str, intent: str) -> Literal["trivial", "complex"]:
    """Return 'trivial' for single-op, clearly-scoped requests; 'complex' otherwise."""
    from langchain_core.messages import HumanMessage

    from vlm_photo_editor.models.registry import build_client

    try:
        client = build_client("cost_router")
        prompt = (
            f"Mode: {mode}\nIntent: {intent}\n\n"
            "Is this a simple, single-step photo edit (e.g. brightness, crop, rotate)? "
            "Reply with exactly one word: TRIVIAL or COMPLEX."
        )
        response = client.invoke([HumanMessage(content=prompt)])
        text = getattr(response, "content", "") or ""
        return "trivial" if "TRIVIAL" in text.upper() else "complex"
    except Exception as exc:
        _log.warning("cost_router unavailable (%s); defaulting to complex", exc)
        return "complex"
