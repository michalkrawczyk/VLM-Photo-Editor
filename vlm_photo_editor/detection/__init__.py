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
    "detector_has_label",
    "detector_labels",
    "install_backend_deps",
    "ready_backends",
    "requires_classes_txt",
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

# Backends that additionally require a sibling ``classes.txt`` (with a human/person
# class) next to their model file before they count as ready. Single switch — add
# u2netp/mediapipe here if they ever grow an enumerable sibling vocabulary.
_CLASSES_REQUIRED: set[str] = {CharacterFocusBackend.YOLO_ONNX.value}


def requires_classes_txt(backend: str) -> bool:
    """True when *backend* needs a sibling ``classes.txt`` to be usable."""
    return backend in _CLASSES_REQUIRED


def ready_backends() -> list[str]:
    """Backends whose package is importable AND whose model-path setting resolves.

    These are the ones safe to offer in the main flow — selecting any other backend
    would guarantee a misconfiguration ``ValueError`` from ``detect_subject()``. For
    a backend in ``_CLASSES_REQUIRED`` the sibling ``classes.txt`` must also exist
    and name a human/person class.
    """
    from vlm_photo_editor.config.settings import get_settings

    from ._common import has_human_label, load_class_labels

    settings = get_settings()
    result: list[str] = []
    for backend in available_backends():
        path = getattr(settings, _BACKEND_PATH_ATTR[backend], None)
        if not path:
            continue
        if backend in _CLASSES_REQUIRED:
            try:
                labels = load_class_labels(path)
            except ValueError:
                continue
            if not has_human_label(labels):
                continue
        result.append(backend)
    return result


def detector_labels(backend: str) -> list[str] | None:
    """Class names *backend* can emit, or ``None`` when its vocabulary is not enumerable.

    ``None`` for ``off``/unknown, for mediapipe (labels live in the tflite metadata,
    not introspected here), and for u2netp (class-agnostic saliency). For a
    classes.txt-backed backend, returns the parsed list or ``None`` when the file is
    absent/unreadable (a non-raising probe — ``ready_backends()`` is where that
    becomes a hard exclusion).
    """
    if backend not in _BACKEND_PATH_ATTR or backend not in _CLASSES_REQUIRED:
        return None
    from vlm_photo_editor.config.settings import get_settings

    from ._common import load_class_labels

    path = getattr(get_settings(), _BACKEND_PATH_ATTR[backend], None)
    if not path:
        return None
    try:
        return load_class_labels(path)
    except ValueError:
        return None


def detector_has_label(backend: str, label: str) -> bool:
    """True when *backend* has an enumerable vocabulary that contains *label*.

    Case-insensitive. A backend whose vocabulary is not enumerable (mediapipe,
    u2netp, ``off``) is treated as *not* having the label — this is what gates the
    ``face_only`` framing option.
    """
    labels = detector_labels(backend)
    if labels is None:
        return False
    return label.strip().casefold() in {name.strip().casefold() for name in labels}


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
