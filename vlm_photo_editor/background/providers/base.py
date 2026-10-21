from __future__ import annotations

import io
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from PIL import Image

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
    ) -> list[Candidate]:
        """Return ``n`` regenerated candidates for the ``mask`` region of ``container``.

        ``mask`` is a bool ``(H, W)`` array, True where the model may regenerate.
        Honouring it is mandatory (BG-P3): regenerate only that region — via a native
        mask/inpaint parameter or by sending only the masked crop. A model that
        cannot inpaint must raise here, not return a full-frame regeneration.

        Each ``Candidate.genai_op`` records ``model``/``prompt``/``seed``. If the
        backing API accepts no seed, record ``seed=None`` — never a fabricated value
        (BG-P2).
        """
        ...


# --- shared provider helpers (BG-C1: were duplicated verbatim across providers) ---


def strip_model_prefix(model: str, prefix: str) -> str:
    """Drop a ``provider:`` routing prefix if present (e.g. ``openai:gpt-image-1``)."""
    return model[len(prefix) :] if model.startswith(prefix) else model


def _to_uint8(pixels: np.ndarray) -> np.ndarray:
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    return pixels


def container_to_pil(container: ImageContainer) -> Image.Image:
    return Image.fromarray(_to_uint8(container.pixels)).convert("RGB")


def container_to_png_bytes(container: ImageContainer) -> bytes:
    buf = io.BytesIO()
    container_to_pil(container).save(buf, format="PNG")
    return buf.getvalue()


def mask_to_l_pil(mask: np.ndarray) -> Image.Image:
    """Mode-``L`` mask: 255 inside the fill region, 0 outside (Replicate/diffusers)."""
    return Image.fromarray((mask.astype(np.uint8) * 255), mode="L")


def mask_to_l_png_bytes(mask: np.ndarray) -> bytes:
    buf = io.BytesIO()
    mask_to_l_pil(mask).save(buf, format="PNG")
    return buf.getvalue()


def mask_to_alpha_png_bytes(mask: np.ndarray) -> bytes:
    """RGBA mask for APIs that edit the ``alpha == 0`` region (OpenAI images.edit).

    Inside the mask (region to regenerate) -> alpha 0; outside -> alpha 255 (BG-B6).
    """
    h, w = mask.shape[:2]
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    inside = mask.astype(bool)
    rgba[..., 3] = np.where(inside, 0, 255)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def decode_to_container(data: bytes, source: ImageContainer) -> ImageContainer:
    """Decode PNG/JPEG bytes into an ImageContainer matching *source*'s geometry."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return pil_to_container(img, source)


def pil_to_container(img: Image.Image, source: ImageContainer) -> ImageContainer:
    img = img.convert("RGB")
    if img.size != (source.width, source.height):
        img = img.resize((source.width, source.height), Image.Resampling.LANCZOS)
    pixels = np.array(img, dtype=np.uint8)
    if source.pixels.dtype == np.uint16:
        # BG-B2: widen 0-255 to 0-65535 (x * 257), not just retype it.
        pixels = pixels.astype(np.uint16) * 257
    return ImageContainer(
        pixels=pixels,
        bit_depth=source.bit_depth,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=dict(source.metadata),
    )


def expand_seeds(seed: int | None, n: int) -> list[int]:
    """A fixed seed → one entry; otherwise *n* fresh random seeds."""
    if seed is not None:
        return [seed]
    return [random.randint(0, 2**31 - 1) for _ in range(n)]
