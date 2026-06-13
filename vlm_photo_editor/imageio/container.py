from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class ImageContainer:
    pixels: np.ndarray       # HxWxC uint8 or uint16
    bit_depth: int           # 8 or 16
    source_path: Path
    icc_profile: bytes | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def channels(self) -> int:
        return int(self.pixels.shape[2]) if self.pixels.ndim == 3 else 1

    def copy(self) -> "ImageContainer":
        return ImageContainer(
            pixels=self.pixels.copy(),
            bit_depth=self.bit_depth,
            source_path=self.source_path,
            icc_profile=self.icc_profile,
            metadata=dict(self.metadata),
        )
