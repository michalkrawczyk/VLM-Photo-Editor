from __future__ import annotations

import numpy as np

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import (
    Candidate,
    GenAIProvider,
    container_to_pil,
    expand_seeds,
    mask_to_l_pil,
    pil_to_container,
    strip_model_prefix,
)

_MODEL_PREFIX = "hf:"


def _is_flux_model(model: str) -> bool:
    return "flux" in model.lower()


def _is_qwen_model(model: str) -> bool:
    return "qwen" in model.lower()


class HuggingFaceProvider(GenAIProvider):
    """Local inference via diffusers (FLUX.1-Fill) or transformers (Qwen2.5-VL)."""

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
        bare_model = strip_model_prefix(model, _MODEL_PREFIX)

        if _is_flux_model(bare_model):
            return self._generate_flux(
                container, mask, prompt, bare_model, step_id, n, seed, **kwargs
            )
        if _is_qwen_model(bare_model):
            return self._generate_qwen(
                container, mask, prompt, bare_model, step_id, n, seed, **kwargs
            )

        raise ValueError(
            f"HuggingFaceProvider: unrecognized model {model!r}. "
            "Supported: FLUX.1-Fill-dev, Qwen2.5-VL variants."
        )

    def _generate_flux(
        self,
        container: ImageContainer,
        mask: np.ndarray,
        prompt: str,
        model: str,
        step_id: str,
        n: int,
        seed: int | None,
        **kwargs,
    ) -> list[Candidate]:
        try:
            import torch
            from diffusers import FluxFillPipeline
        except ImportError as exc:
            raise ImportError(
                "diffusers and torch required for FLUX local inference. "
                "Run: pip install diffusers torch"
            ) from exc

        pipe = FluxFillPipeline.from_pretrained(model, torch_dtype=torch.bfloat16)
        pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")

        image_pil = container_to_pil(container)
        mask_pil = mask_to_l_pil(mask)
        seeds = expand_seeds(seed, n)

        candidates: list[Candidate] = []
        for s in seeds:
            # BG-B8: the generator must live on the pipeline's device or diffusers
            # errors on the mismatch / silently ignores the seed on the GPU sampler.
            generator = torch.Generator(device=pipe.device).manual_seed(s)
            out = pipe(
                prompt=prompt,
                image=image_pil,
                mask_image=mask_pil,
                generator=generator,
                **kwargs,
            ).images[0]
            candidates.append(
                Candidate(
                    container=pil_to_container(out, container),
                    genai_op=GenAIOp(step_id=step_id, model=f"hf:{model}", prompt=prompt, seed=s),
                )
            )
        return candidates

    def _generate_qwen(
        self,
        container: ImageContainer,
        mask: np.ndarray,
        prompt: str,
        model: str,
        step_id: str,
        n: int,
        seed: int | None,
        **kwargs,
    ) -> list[Candidate]:
        # BG-P3 / BG-B7: Qwen2.5-VL produces text, not pixels, and cannot honour the
        # mask — reject up front instead of loading a multi-GB model and running a
        # generation pass only to raise. `composite()` must never be handed a
        # full-frame regeneration that silently ignored the mask.
        raise NotImplementedError(
            "Qwen2.5-VL produces text, not pixels, and cannot inpaint a masked region. "
            "Use it as a prompt refiner, not a direct image editor; pick a FLUX.1-Fill "
            "model for local inference."
        )
