from __future__ import annotations

import io
import random
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

# Models that use instruction-based editing (no mask input); others are treated as inpainting.
_INSTRUCT_MODEL_PREFIXES = ("qwen",)


def _is_instruct_model(model: str) -> bool:
    lower = model.lower()
    return any(lower.startswith(p) or p in lower for p in _INSTRUCT_MODEL_PREFIXES)


def _container_to_png_bytes(container: ImageContainer) -> bytes:
    pixels = container.pixels
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mask_to_png_bytes(mask: np.ndarray) -> bytes:
    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _url_to_container(url_or_bytes: Any, source: ImageContainer) -> ImageContainer:
    """Decode a Replicate output (URL string or file-like) to ImageContainer."""
    if isinstance(url_or_bytes, str):
        import urllib.request

        with urllib.request.urlopen(url_or_bytes) as resp:
            data = resp.read()
    else:
        data = url_or_bytes.read() if hasattr(url_or_bytes, "read") else bytes(url_or_bytes)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    pixels = np.array(img, dtype=source.pixels.dtype)
    return ImageContainer(
        pixels=pixels,
        bit_depth=source.bit_depth,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=dict(source.metadata),
    )


@dataclass
class Candidate:
    container: ImageContainer
    genai_op: GenAIOp


class Generator:
    def __init__(self, replicate_client=None) -> None:
        self._client = replicate_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        import replicate

        return replicate

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
        """Generate N background candidates.

        If seed is provided (replay mode), n is forced to 1 and that seed is reused.
        kwargs are forwarded to the Replicate model input.
        """
        client = self._get_client()
        instruct = (
            kwargs.pop("model_type", "instruct" if _is_instruct_model(model) else "inpaint")
            == "instruct"
        )

        image_bytes = _container_to_png_bytes(container)
        mask_bytes = _mask_to_png_bytes(mask)

        if seed is not None:
            seeds = [seed]
        else:
            seeds = [random.randint(0, 2**31 - 1) for _ in range(n)]

        candidates: list[Candidate] = []
        for s in seeds:
            inp: dict[str, Any] = {"prompt": prompt, "seed": s, **kwargs}
            if instruct:
                inp["image"] = io.BytesIO(image_bytes)
            else:
                inp["image"] = io.BytesIO(image_bytes)
                inp["mask"] = io.BytesIO(mask_bytes)

            output = client.run(model, input=inp)
            # Replicate returns a list of outputs or a single output
            raw = output[0] if isinstance(output, (list, tuple)) else output
            result_container = _url_to_container(raw, container)

            candidates.append(
                Candidate(
                    container=result_container,
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=s),
                )
            )

        return candidates
