from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp


@dataclass
class Candidate:
    container: ImageContainer
    genai_op: GenAIOp


class GenAIProvider(ABC):
    @abstractmethod
    def generate(
        self,
        container: ImageContainer,
        mask: np.ndarray,
        prompt: str,
        model: str,
        step_id: str,
        n: int = 3,
        seed: int | None = None,
        **kwargs,
    ) -> list[Candidate]: ...
