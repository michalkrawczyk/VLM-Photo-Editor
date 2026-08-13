from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import Candidate, GenAIProvider

_MODEL_PREFIX = "openai:"


def _strip_prefix(model: str) -> str:
    return model[len(_MODEL_PREFIX) :] if model.startswith(_MODEL_PREFIX) else model


def _container_to_png_bytes(container: ImageContainer) -> bytes:
    pixels = container.pixels
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def _mask_to_png_bytes(mask: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _bytes_to_container(data: bytes, source: ImageContainer) -> ImageContainer:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.size != (source.width, source.height):
        img = img.resize((source.width, source.height), Image.Resampling.LANCZOS)
    pixels = np.array(img, dtype=source.pixels.dtype)
    return ImageContainer(
        pixels=pixels,
        bit_depth=source.bit_depth,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=dict(source.metadata),
    )


class OpenAIProvider(GenAIProvider):
    """Image editing via OpenAI images.edit API (gpt-image-1, dall-e-2)."""

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
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("openai package required. Run: pip install openai") from exc

        from vlm_photo_editor.secrets.store import SecretStore

        client = OpenAI(api_key=SecretStore.get("openai"))
        bare_model = _strip_prefix(model)

        image_bytes = _container_to_png_bytes(container)
        mask_bytes = _mask_to_png_bytes(mask)

        # OpenAI images.edit doesn't accept a seed; n controls variation count.
        actual_n = 1 if seed is not None else n
        response = client.images.edit(
            model=bare_model,
            image=("image.png", io.BytesIO(image_bytes), "image/png"),
            mask=("mask.png", io.BytesIO(mask_bytes), "image/png"),
            prompt=prompt,
            n=actual_n,
            response_format="b64_json",
            **kwargs,
        )

        import base64

        seeds = (
            [seed] if seed is not None else [random.randint(0, 2**31 - 1) for _ in range(actual_n)]
        )
        candidates: list[Candidate] = []
        for i, image_data in enumerate(response.data):
            data = base64.b64decode(image_data.b64_json)
            candidates.append(
                Candidate(
                    container=_bytes_to_container(data, container),
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=seeds[i]),
                )
            )
        return candidates
