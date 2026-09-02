from __future__ import annotations

import io

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import (
    Candidate,
    GenAIProvider,
    container_to_png_bytes,
    decode_to_container,
    mask_to_alpha_png_bytes,
    strip_model_prefix,
)

_MODEL_PREFIX = "openai:"


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
        bare_model = strip_model_prefix(model, _MODEL_PREFIX)

        image_bytes = container_to_png_bytes(container)
        # BG-B6: images.edit regenerates the transparent (alpha==0) region.
        mask_bytes = mask_to_alpha_png_bytes(mask)

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

        # BG-P2: images.edit accepts no seed — record seed=None, not a fabricated value.
        candidates: list[Candidate] = []
        for image_data in response.data:
            data = base64.b64decode(image_data.b64_json)
            candidates.append(
                Candidate(
                    container=decode_to_container(data, container),
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=None),
                )
            )
        return candidates
