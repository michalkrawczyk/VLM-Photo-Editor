from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppSettings:
    seam_quality_threshold: float = 0.15
    cache_ttl_seconds: int = 3600
    max_background_candidates: int = 3
    output_dir: Path = field(default_factory=lambda: Path("output"))
    recipes_dir: Path = field(default_factory=lambda: Path("recipes"))


_settings = AppSettings()


def get_settings() -> AppSettings:
    return _settings


@dataclass
class DebugSettings:
    vlm_prompt_debug: bool = True


_debug = DebugSettings()


def get_debug_settings() -> DebugSettings:
    return _debug
