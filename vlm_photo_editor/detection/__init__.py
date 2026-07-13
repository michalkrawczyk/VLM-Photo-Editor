from __future__ import annotations

import importlib.util

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import CharacterFocusBackend

__all__ = ["available_backends", "detect_subject"]


def available_backends() -> list[str]:
    """Return Character Focus backend names whose packages are importable."""
    result: list[str] = []
    if importlib.util.find_spec("mediapipe") is not None:
        result.append(CharacterFocusBackend.MEDIAPIPE.value)
    if importlib.util.find_spec("onnxruntime") is not None:
        result.append(CharacterFocusBackend.YOLO_ONNX.value)
        result.append(CharacterFocusBackend.U2NETP.value)
    return result


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
