from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class AppSettings:
    seam_quality_threshold: float = 0.15
    cache_ttl_seconds: int = 3600
    max_background_candidates: int = 3
    output_dir: Path = field(default_factory=lambda: Path("output"))
    recipes_dir: Path = field(default_factory=lambda: Path("recipes"))
    # When True, planner must not propose Backend.GENAI for inpaint ops;
    # compiler falls back GENAI → OPENCV as a safety net.
    no_genai: bool = False
    # PS mode: "auto" = normal, "strict" = PS-expressible ops only, "none" = no PS backend.
    ps_mode: Literal["auto", "strict", "none"] = "auto"
    # Default model for GENAI inpaint/background ops (can be overridden per-op via params["model"]).
    genai_model: str = "black-forest-labs/flux-fill-dev"
    # Retries after first crop-bounds failure (not counting initial attempt).
    max_crop_retries: int = 3
    # Character Focus (P13) detector model files — no auto-download, user supplies the path.
    mediapipe_model_path: str | None = None
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
