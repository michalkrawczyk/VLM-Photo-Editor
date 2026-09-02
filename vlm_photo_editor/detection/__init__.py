from __future__ import annotations

import importlib.util
import subprocess
import sys

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import CharacterFocusBackend

__all__ = ["available_backends", "detect_subject", "install_backend_deps"]


def available_backends() -> list[str]:
    """Return Character Focus backend names whose packages are importable."""
    result: list[str] = []
    if importlib.util.find_spec("mediapipe") is not None:
        result.append(CharacterFocusBackend.MEDIAPIPE.value)
    if importlib.util.find_spec("onnxruntime") is not None:
        result.append(CharacterFocusBackend.YOLO_ONNX.value)
        result.append(CharacterFocusBackend.U2NETP.value)
    return result


_BACKEND_REQS: dict[str, str] = {
    CharacterFocusBackend.MEDIAPIPE.value: "requirements-mediapipe.txt",
    CharacterFocusBackend.YOLO_ONNX.value: "requirements-onnxruntime.txt",
    CharacterFocusBackend.U2NETP.value: "requirements-onnxruntime.txt",
}


def install_backend_deps(backend: str) -> tuple[bool, str]:
    """Run pip install for the given Character Focus backend's requirements file.

    Returns ``(ok, output_tail)`` — on failure ``output_tail`` carries pip's
    captured stderr/stdout so the caller can show it instead of pointing the
    user at a terminal that never received it.
    """
    if backend not in _BACKEND_REQS:
        raise ValueError(f"Unknown backend: {backend!r}. Available: {sorted(_BACKEND_REQS)}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", _BACKEND_REQS[backend]],
        capture_output=True,
        text=True,
    )
    output = (result.stderr or "") + (result.stdout or "")
    return result.returncode == 0, output.strip()[-4000:]


def detect_subject(container: ImageContainer, backend: str) -> DetectedSubject:
    """Run the given Character Focus backend's detector once on *container*."""
    resolved = CharacterFocusBackend(backend)
    if resolved is CharacterFocusBackend.OFF:
        raise ValueError("detect_subject() called with backend='off'; caller should skip detection")
    if resolved is CharacterFocusBackend.MEDIAPIPE:
        from . import mediapipe_backend

        return mediapipe_backend.detect(container)
    if resolved is CharacterFocusBackend.YOLO_ONNX:
        from . import yolo_onnx_backend

        return yolo_onnx_backend.detect(container)
    from . import u2netp_backend

    return u2netp_backend.detect(container)
