from __future__ import annotations

import io

import numpy as np
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import (
    Candidate,
    GenAIProvider,
    container_to_pil,
    pil_to_container,
    strip_model_prefix,
)

_MODEL_PREFIX = "google:"


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) tight bounding box of the True region. Raises if empty."""
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        raise ValueError("GoogleProvider: mask is empty; nothing to regenerate")
    y0, y1 = np.where(rows)[0][[0, -1]]
    x0, x1 = np.where(cols)[0][[0, -1]]
    return int(x0), int(y0), int(x1) + 1, int(y1) + 1


class GoogleProvider(GenAIProvider):
    """Image editing via Google Imagen (google-generativeai SDK).

    BG-P3: the SDK exposes no mask parameter, so the mask is honoured by only ever
    sending the model the cropped bounding box of the masked region. Subject pixels
    (outside that box) never leave the client and are copied through byte-identical;
    ``composite()`` then feathers the regenerated region back over the full mask.
    """

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
        bare_model = strip_model_prefix(model, _MODEL_PREFIX)

        x0, y0, x1, y1 = _mask_bbox(mask)
        full_pil = container_to_pil(container)
        region_pil = full_pil.crop((x0, y0, x1, y1))

        buf = io.BytesIO()
        region_pil.save(buf, format="PNG")

        actual_n = 1 if seed is not None else n

        client = genai.ImageGenerationModel(bare_model)
        response = client.edit_image(
            prompt=prompt,
            base_image=genai.types.Image(image_bytes=buf.getvalue()),
            number_of_images=actual_n,
            **kwargs,
        )

        region_size = (x1 - x0, y1 - y0)
        candidates: list[Candidate] = []
        for generated in response.generated_images:
            gen_region = Image.open(io.BytesIO(generated.image.image_bytes)).convert("RGB")
            if gen_region.size != region_size:
                gen_region = gen_region.resize(region_size, Image.Resampling.LANCZOS)
            out_pil = full_pil.copy()
            out_pil.paste(gen_region, (x0, y0))
            candidates.append(
                Candidate(
                    container=pil_to_container(out_pil, container),
                    # BG-P2: Imagen edit accepts no seed — record None, not a fabricated value.
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=None),
                )
            )
        return candidates
