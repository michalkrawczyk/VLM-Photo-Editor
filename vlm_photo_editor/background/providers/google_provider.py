from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import Candidate, GenAIProvider

_MODEL_PREFIX = "google:"


def _strip_prefix(model: str) -> str:
    return model[len(_MODEL_PREFIX) :] if model.startswith(_MODEL_PREFIX) else model


def _container_to_pil(container: ImageContainer) -> Image.Image:
    pixels = container.pixels
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    return Image.fromarray(pixels).convert("RGB")


def _pil_to_container(img: Image.Image, source: ImageContainer) -> ImageContainer:
    pixels = np.array(img.convert("RGB"), dtype=source.pixels.dtype)
    return ImageContainer(
        pixels=pixels,
        bit_depth=source.bit_depth,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=dict(source.metadata),
    )


class GoogleProvider(GenAIProvider):
    """Image editing via Google Imagen (google-generativeai SDK)."""

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
        try:
            from google import generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "google-generativeai package required. Run: pip install google-generativeai"
            ) from exc

        from vlm_photo_editor.secrets.store import SecretStore

        genai.configure(api_key=SecretStore.get("google"))
        bare_model = _strip_prefix(model)

        image_pil = _container_to_pil(container)
        buf = io.BytesIO()
        image_pil.save(buf, format="PNG")
        buf.seek(0)
        image_part = {"mime_type": "image/png", "data": buf.getvalue()}

        actual_n = 1 if seed is not None else n
        seeds = (
            [seed] if seed is not None else [random.randint(0, 2**31 - 1) for _ in range(actual_n)]
        )

        client = genai.ImageGenerationModel(bare_model)
        response = client.edit_image(
            prompt=prompt,
            base_image=genai.types.Image(image_bytes=image_part["data"]),
            number_of_images=actual_n,
            **kwargs,
        )

        candidates: list[Candidate] = []
        for i, generated in enumerate(response.generated_images):
            img = Image.open(io.BytesIO(generated.image.image_bytes)).convert("RGB")
            candidates.append(
                Candidate(
                    container=_pil_to_container(img, container),
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=seeds[i]),
                )
            )
        return candidates
