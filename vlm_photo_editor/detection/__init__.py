from __future__ import annotations

import importlib.util
import subprocess
import sys

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import CharacterFocusBackend

__all__ = [
    "available_backends",
    "detect_subject",
    "install_backend_deps",
    "ready_backends",
]


def available_backends() -> list[str]:
    """Return Character Focus backend names whose packages are importable."""
    result: list[str] = []
    if importlib.util.find_spec("mediapipe") is not None:
        result.append(CharacterFocusBackend.MEDIAPIPE.value)
    if importlib.util.find_spec("onnxruntime") is not None:
        result.append(CharacterFocusBackend.YOLO_ONNX.value)
        result.append(CharacterFocusBackend.U2NETP.value)
    return result


_BACKEND_PATH_ATTR: dict[str, str] = {
    CharacterFocusBackend.MEDIAPIPE.value: "mediapipe_model_path",
    CharacterFocusBackend.YOLO_ONNX.value: "yolo_onnx_model_path",
    CharacterFocusBackend.U2NETP.value: "u2netp_model_path",
}


def ready_backends() -> list[str]:
    """Backends whose package is importable AND whose model-path setting resolves.

    These are the ones safe to offer in the main flow — selecting any other backend
    would guarantee a misconfiguration ``ValueError`` from ``detect_subject()``.
    """
    from vlm_photo_editor.config.settings import get_settings

    settings = get_settings()
    return [
        backend
        for backend in available_backends()
        if getattr(settings, _BACKEND_PATH_ATTR[backend], None)
    ]


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


# DET-P1: coarse floor below which a detection is not trusted to define the
# subject-freeze region. Scores are NOT comparable across backends (DET-P3), so this
# is deliberately low — it mainly rejects the mediapipe `category is None -> 0.0`
# fallback and any pathological near-zero score.
_MIN_CONFIDENCE = 0.25


def detect_subject(container: ImageContainer, backend: str) -> DetectedSubject | None:
    """Run the given Character Focus backend's detector once on *container*.

    Returns ``None`` when the detector ran cleanly but found no subject (DET-P2) or
    when the best detection scores below ``_MIN_CONFIDENCE`` (DET-P1); raises
    ``ValueError`` only for misconfiguration (unknown/off backend, missing model
    path).
    """
    resolved = CharacterFocusBackend(backend)
    if resolved is CharacterFocusBackend.OFF:
        raise ValueError("detect_subject() called with backend='off'; caller should skip detection")
    if resolved is CharacterFocusBackend.MEDIAPIPE:
        from . import mediapipe_backend

        result = mediapipe_backend.detect(container)
    elif resolved is CharacterFocusBackend.YOLO_ONNX:
        from . import yolo_onnx_backend

        result = yolo_onnx_backend.detect(container)
    else:
        from . import u2netp_backend

        result = u2netp_backend.detect(container)

    if result is not None and result.confidence < _MIN_CONFIDENCE:
        return None
    return result
