"""Detector-model registry: legacy settings slots + scanned bundles + user-added paths.

Everything is recomputed per call (cheap: a handful of small files) so a dropped-in
model dir or a changed ``AppSettings.*_model_path`` shows up without a restart.
"""

from __future__ import annotations

import importlib.util
import json
import re
import zipfile
from pathlib import Path
from typing import Any, get_args

from vlm_photo_editor.schema.detection import DetectorLayout, DetectorModel, DetectorOrigin
from vlm_photo_editor.schema.ops import CharacterFocusBackend

from ._common import has_human_label, human_labels, load_class_labels

__all__ = [
    "add_user_model",
    "get_model",
    "list_models",
    "model_has_label",
    "model_has_person",
    "model_labels",
    "model_person_labels",
    "ready_models",
    "remove_user_model",
]

# Legacy single-slot backends: model id == backend name, path from AppSettings.
_LEGACY_PATH_ATTR: dict[str, str] = {
    CharacterFocusBackend.MEDIAPIPE.value: "mediapipe_model_path",
    CharacterFocusBackend.YOLO_ONNX.value: "yolo_onnx_model_path",
    CharacterFocusBackend.U2NETP.value: "u2netp_model_path",
}
# Backends whose package must be importable (mediapipe vs onnxruntime).
_BACKEND_PACKAGE: dict[str, str] = {
    CharacterFocusBackend.MEDIAPIPE.value: "mediapipe",
    CharacterFocusBackend.YOLO_ONNX.value: "onnxruntime",
    CharacterFocusBackend.U2NETP.value: "onnxruntime",
}
# Backends whose vocabulary must come from a sibling classes.txt.
_CLASSES_TXT_BACKENDS = frozenset({CharacterFocusBackend.YOLO_ONNX.value})
_VALID_LAYOUTS = frozenset(get_args(DetectorLayout))
_MODEL_SUFFIXES = (".onnx", ".tflite")


def _settings():
    from vlm_photo_editor.config.settings import get_settings

    return get_settings()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_") or "model"


def _unique_id(base: str, taken: set[str]) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _tflite_labels(path: Path) -> list[str] | None:
    """Labels embedded in a tflite-metadata zip (``labels*.txt``), else ``None``."""
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.casefold().endswith(".txt") and "label" in name.casefold():
                    lines = [ln.strip() for ln in zf.read(name).decode("utf-8").splitlines()]
                    while lines and not lines[-1]:
                        lines.pop()
                    return lines or None
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, KeyError):
        return None
    return None


def _resolve_labels(backend: str, path: Path) -> tuple[list[str] | None, str | None]:
    """Return ``(labels, invalid_reason)`` for a model file."""
    if backend in _CLASSES_TXT_BACKENDS:
        try:
            return load_class_labels(path), None
        except ValueError as exc:
            return None, str(exc)
    if backend == CharacterFocusBackend.MEDIAPIPE.value:
        labels = _tflite_labels(path)
        if labels is not None:
            return labels, None
        try:
            return load_class_labels(path), None
        except ValueError:
            return None, None  # class-agnostic: no enumerable vocabulary
    return None, None


def _infer_backend(path: Path, has_classes_txt: bool) -> str | None:
    if path.suffix.casefold() == ".tflite":
        return CharacterFocusBackend.MEDIAPIPE.value
    if path.suffix.casefold() == ".onnx" and has_classes_txt:
        return CharacterFocusBackend.YOLO_ONNX.value
    return None


def _build_model(
    *,
    model_id: str,
    display_name: str,
    backend: object,
    path: Path,
    origin: DetectorOrigin,
    manifest: dict[str, Any],
) -> DetectorModel:
    """Validate one file + manifest into a ``DetectorModel`` (never raises)."""
    reason: str | None = None
    if not isinstance(backend, str):
        backend = None
    layout = manifest.get("layout", "yolov8")
    if layout not in _VALID_LAYOUTS:
        reason = f"model.json layout {layout!r} unknown; use one of {sorted(_VALID_LAYOUTS)}"
        layout = "yolov8"
    if backend not in _BACKEND_PACKAGE:
        backend_enum = CharacterFocusBackend.OFF
        reason = reason or (
            "backend unknown: an .onnx model needs a sibling classes.txt (detector) or "
            'a model.json {"backend": "u2netp"} (saliency)'
        )
        labels = None
    else:
        backend_enum = CharacterFocusBackend(backend)
        labels, label_reason = _resolve_labels(backend, path)
        reason = reason or label_reason
    if reason is None and not path.is_file():
        reason = f"model file not found: {path}"
    try:
        return DetectorModel(
            id=model_id,
            display_name=display_name,
            backend=backend_enum,
            path=str(path),
            labels=labels,
            origin=origin,
            layout=layout,
            input_size=manifest.get("input_size"),
            conf_threshold=manifest.get("conf_threshold"),
            invalid_reason=reason,
        )
    except ValueError as exc:  # bad input_size / conf_threshold in model.json
        return DetectorModel(
            id=model_id,
            display_name=display_name,
            backend=backend_enum,
            path=str(path),
            labels=labels,
            origin=origin,
            invalid_reason=f"model.json invalid: {exc}",
        )


def _read_manifest(directory: Path) -> dict[str, Any]:
    manifest_file = directory / "model.json"
    if not manifest_file.is_file():
        return {}
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"layout": "<unreadable model.json>"}
    return data if isinstance(data, dict) else {"layout": "<model.json is not an object>"}


def _legacy_models() -> list[DetectorModel]:
    settings = _settings()
    models: list[DetectorModel] = []
    for backend, attr in _LEGACY_PATH_ATTR.items():
        path = getattr(settings, attr, None)
        if not path:
            models.append(
                DetectorModel(
                    id=backend,
                    display_name=backend,
                    backend=CharacterFocusBackend(backend),
                    origin="legacy",
                    invalid_reason=(
                        f"Character Focus backend {backend!r} requires "
                        f"AppSettings.{attr} to be set to a model file."
                    ),
                )
            )
            continue
        labels, reason = _resolve_labels(backend, Path(path))
        models.append(
            DetectorModel(
                id=backend,
                display_name=backend,
                backend=CharacterFocusBackend(backend),
                path=str(path),
                labels=labels,
                origin="legacy",
                invalid_reason=reason,
            )
        )
    return models


def _discovered_models(taken_ids: set[str], taken_paths: set[str]) -> list[DetectorModel]:
    root = Path(_settings().detector_models_dir)
    if not root.is_dir():
        return []
    models: list[DetectorModel] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(f for f in directory.iterdir() if f.suffix.casefold() in _MODEL_SUFFIXES)
        if not files:
            continue
        manifest = _read_manifest(directory)
        for file in files:
            if str(file) in taken_paths:
                continue  # already offered as a legacy slot
            backend = manifest.get("backend") or _infer_backend(
                file, (directory / "classes.txt").is_file()
            )
            base = _slug(directory.name if len(files) == 1 else f"{directory.name}_{file.stem}")
            model_id = _unique_id(base, taken_ids)
            taken_ids.add(model_id)
            models.append(
                _build_model(
                    model_id=model_id,
                    display_name=str(manifest.get("name") or directory.name),
                    backend=backend,
                    path=file,
                    origin="discovered",
                    manifest=manifest,
                )
            )
    return models


def _read_user_entries() -> list[dict[str, Any]]:
    file = Path(_settings().detectors_file)
    if not file.is_file():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    entries = data.get("models") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _write_user_entries(entries: list[dict[str, Any]]) -> None:
    file = Path(_settings().detectors_file)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"models": entries}, indent=2), encoding="utf-8")


def _user_models(taken_ids: set[str]) -> list[DetectorModel]:
    models: list[DetectorModel] = []
    for entry in _read_user_entries():
        path_text, model_id = entry.get("path"), entry.get("id")
        if not isinstance(path_text, str) or not isinstance(model_id, str):
            continue
        if model_id in taken_ids:
            continue
        taken_ids.add(model_id)
        path = Path(path_text)
        models.append(
            _build_model(
                model_id=model_id,
                display_name=str(entry.get("name") or path.stem),
                backend=entry.get("backend"),
                path=path,
                origin="user",
                manifest=entry,
            )
        )
    return models


def list_models() -> list[DetectorModel]:
    """All known models (valid or not): legacy slots, scanned bundles, user-added."""
    legacy = _legacy_models()
    taken_ids = {m.id for m in legacy}
    taken_paths = {m.path for m in legacy if m.path}
    discovered = _discovered_models(taken_ids, taken_paths)
    return legacy + discovered + _user_models(taken_ids)


def get_model(model_id: str) -> DetectorModel | None:
    return next((m for m in list_models() if m.id == model_id), None)


def model_is_ready(model: DetectorModel) -> bool:
    """Package importable and no ``invalid_reason``.

    A legacy slot only needs its path setting to resolve (no file-exists check —
    matches the pre-registry contract); scanned/user models also need the file.
    """
    package = _BACKEND_PACKAGE.get(model.backend.value)
    if package is None or importlib.util.find_spec(package) is None:
        return False
    return model.invalid_reason is None and bool(model.path)


def ready_models() -> list[DetectorModel]:
    return [m for m in list_models() if model_is_ready(m)]


def model_labels(model_id: str) -> list[str] | None:
    model = get_model(model_id)
    return None if model is None else model.labels


def model_has_label(model_id: str, label: str) -> bool:
    """Case-insensitive; class-agnostic/unknown models never have a label."""
    labels = model_labels(model_id)
    if labels is None:
        return False
    return label.strip().casefold() in {name.strip().casefold() for name in labels}


def model_has_person(model_id: str) -> bool:
    labels = model_labels(model_id)
    return labels is not None and has_human_label(labels)


def model_person_labels(model_id: str) -> list[str]:
    """The model's human/person class names (empty when none / not enumerable)."""
    labels = model_labels(model_id)
    return [] if labels is None else human_labels(labels)


def add_user_model(path: str, name: str = "", backend: str | None = None) -> DetectorModel:
    """Register a model file the user keeps outside the scanned directory.

    Returns the resulting entry (possibly with ``invalid_reason``). Raises
    ``ValueError`` for an unsupported file type or a duplicate path — the caller
    shows it, nothing is written.
    """
    file = Path(path).expanduser()
    if file.suffix.casefold() not in _MODEL_SUFFIXES:
        raise ValueError(f"Unsupported model file {file.name!r}; expected .onnx or .tflite")
    entries = _read_user_entries()
    if any(e.get("path") == str(file) for e in entries):
        raise ValueError(f"Model already registered: {file}")
    resolved_backend = backend or _infer_backend(file, file.with_name("classes.txt").is_file())
    taken = {m.id for m in list_models()}
    model_id = _unique_id(_slug(name or file.stem), taken)
    entry: dict[str, Any] = {"id": model_id, "name": name or file.stem, "path": str(file)}
    if resolved_backend:
        entry["backend"] = resolved_backend
    _write_user_entries([*entries, entry])
    model = get_model(model_id)
    if model is None:
        raise RuntimeError(f"Registered detector model {model_id!r} vanished after write")
    return model


def remove_user_model(model_id: str) -> None:
    """Drop a user-added entry. Raises ``ValueError`` when *model_id* is not one."""
    entries = _read_user_entries()
    kept = [e for e in entries if e.get("id") != model_id]
    if len(kept) == len(entries):
        raise ValueError(f"No user-added detector model with id {model_id!r}")
    _write_user_entries(kept)
