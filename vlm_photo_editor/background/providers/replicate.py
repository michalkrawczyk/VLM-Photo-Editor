from __future__ import annotations

import io
from typing import Any

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import (
    Candidate,
    GenAIProvider,
    container_to_png_bytes,
    decode_to_container,
    expand_seeds,
    mask_to_l_png_bytes,
)

_INSTRUCT_MODEL_PREFIXES = ("qwen",)


def _is_instruct_model(model: str) -> bool:
    lower = model.lower()
    return any(lower.startswith(p) or p in lower for p in _INSTRUCT_MODEL_PREFIXES)


def _output_to_container(url_or_bytes: Any, source: ImageContainer) -> ImageContainer:
    if isinstance(url_or_bytes, str):
        import urllib.request

        with urllib.request.urlopen(url_or_bytes) as resp:
            data = resp.read()
    elif hasattr(url_or_bytes, "read"):
        data = url_or_bytes.read()
    else:
        data = bytes(url_or_bytes)
    return decode_to_container(data, source)


class ReplicateProvider(GenAIProvider):
    def __init__(self, replicate_client=None) -> None:
        self._client = replicate_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        import replicate

        from vlm_photo_editor.secrets.store import SecretStore

        api_token = SecretStore.get("replicate")
        return replicate.Client(api_token=api_token)

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
        client = self._get_client()
        instruct = (
            kwargs.pop("model_type", "instruct" if _is_instruct_model(model) else "inpaint")
            == "instruct"
        )

        image_bytes = container_to_png_bytes(container)
        mask_bytes = mask_to_l_png_bytes(mask)

        seeds = expand_seeds(seed, n)

        candidates: list[Candidate] = []
        for s in seeds:
            inp: dict[str, Any] = {"prompt": prompt, "seed": s, **kwargs}
            inp["image"] = io.BytesIO(image_bytes)
            if not instruct:
                inp["mask"] = io.BytesIO(mask_bytes)

            output = client.run(model, input=inp)
            raw = output[0] if isinstance(output, (list, tuple)) else output
            result_container = _output_to_container(raw, container)

            candidates.append(
                Candidate(
                    container=result_container,
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=s),
                )
            )

        return candidates
