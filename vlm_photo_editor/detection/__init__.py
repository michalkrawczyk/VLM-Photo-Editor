from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import CharacterFocusBackend

from .registry import (
    _CLASSES_TXT_BACKENDS,
    _LEGACY_PATH_ATTR,
    add_user_model,
    get_model,
    list_models,
    model_has_label,
    model_has_person,
    model_labels,
    model_person_labels,
    ready_models,
    remove_user_model,
)

_LEGACY_IDS = frozenset(_LEGACY_PATH_ATTR)

__all__ = [
    "add_user_model",
    "available_backends",
    "detect_subject",
    "detector_has_label",
    "detector_labels",
    "get_model",
    "install_backend_deps",
    "list_models",
    "model_has_label",
    "model_has_person",
    "model_labels",
    "model_person_labels",
    "ready_backends",
    "ready_models",
    "remove_user_model",
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


def requires_classes_txt(backend: str) -> bool:
    """True when *backend* needs a sibling ``classes.txt`` to be usable."""
    return backend in _CLASSES_TXT_BACKENDS


# Legacy single-slot API: a backend name is also the id of its settings-path model.
def ready_backends() -> list[str]:
    """Legacy-slot backends whose package is importable AND whose model is usable.

    Superseded by ``ready_models()`` (which also lists scanned/user-added models);
    kept so callers and tests keyed on backend names keep working.
    """
    return [m.id for m in ready_models() if m.origin == "legacy"]


def detector_labels(backend: str) -> list[str] | None:
    """Class names of the legacy-slot model *backend*, or ``None`` when not enumerable.

    ``None`` for ``off``/unknown ids, class-agnostic models (u2netp), and a
    classes.txt-backed model whose file is absent/unreadable (a non-raising probe —
    ``ready_models()`` is where that becomes a hard exclusion).
    """
    return model_labels(backend) if backend in _LEGACY_IDS else None


def detector_has_label(backend: str, label: str) -> bool:
    """True when legacy-slot *backend* has an enumerable vocabulary containing *label*."""
    return model_has_label(backend, label) if backend in _LEGACY_IDS else False


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


def detect_subject(
    container: ImageContainer, model_id: str, target_labels: Sequence[str] | None = None
) -> DetectedSubject | None:
    """Run the detector model *model_id* once on *container*.

    *model_id* is a ``list_models()`` id; the legacy backend names (``mediapipe`` /
    ``yolo_onnx`` / ``u2netp``) are the ids of the settings-path models. *target_labels*
    restricts detection to those classes (``None``/empty = every class) and requires an
    enumerable-vocabulary model.

    Returns ``None`` when the detector ran cleanly but found no subject (DET-P2) or
    when the best detection scores below ``_MIN_CONFIDENCE`` (DET-P1); raises
    ``ValueError`` only for misconfiguration (unknown/off model, invalid model, unknown
    target class).
    """
    if model_id == CharacterFocusBackend.OFF.value:
        raise ValueError("detect_subject() called with backend='off'; caller should skip detection")
    model = get_model(model_id)
    if model is None:
        known = [m.id for m in list_models()]
        raise ValueError(f"Unknown Character Focus model {model_id!r}. Known: {known}")
    if model.invalid_reason:
        raise ValueError(model.invalid_reason)
    if target_labels and model.labels is None:
        raise ValueError(
            f"Model {model_id!r} has no enumerable classes; "
            f"cannot restrict to {list(target_labels)}"
        )

    if model.backend is CharacterFocusBackend.MEDIAPIPE:
        from . import mediapipe_backend

        result = mediapipe_backend.detect(container, model, target_labels)
    elif model.backend is CharacterFocusBackend.YOLO_ONNX:
        from . import yolo_onnx_backend

        result = yolo_onnx_backend.detect(container, model, target_labels)
    else:
        from . import u2netp_backend

        result = u2netp_backend.detect(container, model)

    if result is not None and result.confidence < _MIN_CONFIDENCE:
        return None
    return result
