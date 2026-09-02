from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


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
    # Character Focus (P13) detector model files — no auto-download, user supplies the path
    # (directly, or via env var for mediapipe_model_path).
    mediapipe_model_path: str | None = field(
        default_factory=lambda: os.environ.get("MEDIAPIPE_MODEL_PATH")
    )
    yolo_onnx_model_path: str | None = None
    u2netp_model_path: str | None = None


_settings = AppSettings()


def get_settings() -> AppSettings:
    return _settings


@dataclass
class DebugSettings:
    vlm_prompt_debug: bool = True


_debug = DebugSettings()


def get_debug_settings() -> DebugSettings:
    return _debug
