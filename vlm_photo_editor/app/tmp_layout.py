"""Structured per-image scratch directories for uploads (plans/issues.md D15).

Layout::

    <tempdir>/vlm_photo_editor/
    └── <image-stem>_<session-id>/
        ├── original.<ext>
        ├── edited.<ext>
        └── <stem>.edit.json

One subfolder per uploaded image, deterministic within a session so the recipe
and output always land together. The previous image's subfolder is swept when a
new image is uploaded, and the whole session tree on session end — so uploads no
longer leak flat into the system temp directory (fixes B5 for this path).
"""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from pathlib import Path

from vlm_photo_editor.app import state

_ROOT = Path(tempfile.gettempdir()) / "vlm_photo_editor"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _session_id() -> str:
    sid = state.get("_tmp_session_id")
    if not sid:
        sid = uuid.uuid4().hex[:12]
        state.set("_tmp_session_id", sid)
    return sid


def image_workdir(stem: str) -> Path:
    """Return (creating) this session's scratch dir for the image named *stem*.

    Sweeps the previous image's scratch dir first.
    """
    safe_stem = _SAFE.sub("_", stem).strip("_") or "image"
    workdir = _ROOT / f"{safe_stem}_{_session_id()}"

    prev = state.get("_tmp_workdir")
    if prev and str(prev) != str(workdir):
        shutil.rmtree(prev, ignore_errors=True)

    workdir.mkdir(parents=True, exist_ok=True)
    state.set("_tmp_workdir", str(workdir))
    return workdir


def sweep_session() -> None:
    """Remove every scratch dir belonging to this session (call on session end)."""
    sid = state.get("_tmp_session_id")
    if not sid or not _ROOT.exists():
        return
    for child in _ROOT.glob(f"*_{sid}"):
        shutil.rmtree(child, ignore_errors=True)
    state.set("_tmp_workdir", None)
