from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Repo-local directory for large, non-redistributable inference model files (gitignored).
_INFER_MODELS_DIR = Path(__file__).resolve().parents[2] / "infer_models"


def _path_setting(env_key: str, bundled_default: Path | None = None) -> str | None:
    """Resolve a model-file path: env var, else ``.env``, else a bundled default.

    ``.env`` is read via ``dotenv_values`` (never ``load_dotenv``) so API keys living
    in the same file are never pushed into ``os.environ`` and inherited by child
    processes (pip installs, the mediapipe probe). No auto-download — returns ``None``
    when nothing resolves.
    """
    value = os.environ.get(env_key)
    if value:
        return value
    try:
        from dotenv import dotenv_values, find_dotenv

        env_file = find_dotenv(usecwd=True)
        if env_file:
            dotenv_val = dotenv_values(env_file).get(env_key)
            if dotenv_val:
                return dotenv_val
    except Exception:
        pass
    if bundled_default is not None and bundled_default.is_file():
        return str(bundled_default)
    return None


@dataclass
class AppSettings:
    # Seam metric gate for genAI background composites (see background/quality.py::seam_metric).
    seam_threshold: float = 10.0
    # Gaussian sigma (px) for the composite seam feather.
    feather_px: int = 20
    cache_ttl_seconds: int = 3600
    max_background_candidates: int = 3
    # Where saved edits and their recipe sidecars land (env-overridable). Never the
    # upload's temp directory — see plans/issues.md D15.
    output_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("VLM_OUTPUT_DIR") or Path.home() / "Pictures" / "vlm_edits"
        )
    )
    recipes_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("VLM_RECIPES_DIR") or Path.home() / "Pictures" / "vlm_edits" / "recipes"
        )
    )
    # When True, planner must not propose Backend.GENAI for inpaint ops;
    # compiler falls back GENAI → OPENCV as a safety net.
    no_genai: bool = False
    # PS mode: "auto" = normal, "strict" = PS-expressible ops only, "none" = no PS backend.
    ps_mode: Literal["auto", "strict", "none"] = "auto"
    # Default model for GENAI inpaint/background ops (can be overridden per-op via params["model"]).
    genai_model: str = "black-forest-labs/flux-fill-dev"
    # Retries after first crop-bounds failure (not counting initial attempt).
    max_crop_retries: int = 3
    # Character Focus (P13) detector model files — no auto-download. Each resolves
    # <NAME>_MODEL_PATH from env, then .env; yolo_onnx also falls back to the bundled
    # infer_models/yolo/yolo26s.onnx when present. See _path_setting().
    # yolo_onnx additionally requires a sibling classes.txt (same directory as the
    # .onnx; one class name per line, 0-based line index == class id) — see
    # detection/_common.py::load_class_labels. These three are the legacy single-slot
    # models; more are scanned from detector_models_dir or user-registered
    # (detection/registry.py).
    mediapipe_model_path: str | None = field(
        default_factory=lambda: _path_setting("MEDIAPIPE_MODEL_PATH")
    )
    yolo_onnx_model_path: str | None = field(
        default_factory=lambda: _path_setting(
            "YOLO_ONNX_MODEL_PATH", _INFER_MODELS_DIR / "yolo" / "yolo26s.onnx"
        )
    )
    u2netp_model_path: str | None = field(
        default_factory=lambda: _path_setting("U2NETP_MODEL_PATH")
    )
    # Pluggable detector models: directory scanned for ``<dir>/<model>.onnx|.tflite``
    # bundles, and the JSON file holding user-registered model paths (paths only).
    detector_models_dir: Path = field(default_factory=lambda: _INFER_MODELS_DIR)
    detectors_file: Path = field(
        default_factory=lambda: Path(
            os.environ.get("VLM_DETECTORS_FILE")
            or Path.home() / ".config" / "vlm_photo_editor" / "detectors.json"
        )
    )


_settings = AppSettings()


def get_settings() -> AppSettings:
    return _settings


@dataclass
class DebugSettings:
    vlm_prompt_debug: bool = True


_debug = DebugSettings()


def get_debug_settings() -> DebugSettings:
    return _debug
