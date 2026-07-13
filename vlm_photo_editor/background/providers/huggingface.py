from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

from .base import Candidate, GenAIProvider

_MODEL_PREFIX = "hf:"


def _strip_prefix(model: str) -> str:
    return model[len(_MODEL_PREFIX) :] if model.startswith(_MODEL_PREFIX) else model


def _is_flux_model(model: str) -> bool:
    return "flux" in model.lower()


def _is_qwen_model(model: str) -> bool:
    return "qwen" in model.lower()


def _container_to_pil(container: ImageContainer) -> Image.Image:
    pixels = container.pixels
    if pixels.dtype != np.uint8:
        pixels = (pixels / 256).clip(0, 255).astype(np.uint8)
    return Image.fromarray(pixels).convert("RGB")


def _mask_to_pil(mask: np.ndarray) -> Image.Image:
    return Image.fromarray((mask.astype(np.uint8) * 255), mode="L")


def _pil_to_container(img: Image.Image, source: ImageContainer) -> ImageContainer:
    pixels = np.array(img.convert("RGB"), dtype=source.pixels.dtype)
    return ImageContainer(
        pixels=pixels,
        bit_depth=source.bit_depth,
        source_path=source.source_path,
        icc_profile=source.icc_profile,
        metadata=dict(source.metadata),
    )


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
        bare_model = _strip_prefix(model)

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

        image_pil = _container_to_pil(container)
        mask_pil = _mask_to_pil(mask)
        seeds = [seed] if seed is not None else [random.randint(0, 2**31 - 1) for _ in range(n)]

        candidates: list[Candidate] = []
        for s in seeds:
            generator = torch.Generator().manual_seed(s)
            out = pipe(
                prompt=prompt,
                image=image_pil,
                mask_image=mask_pil,
                generator=generator,
                **kwargs,
            ).images[0]
            candidates.append(
                Candidate(
                    container=_pil_to_container(out, container),
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
        try:
            import torch
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        except ImportError as exc:
            raise ImportError(
                "transformers and torch required for Qwen local inference. "
                "Run: pip install transformers torch"
            ) from exc

        processor = AutoProcessor.from_pretrained(model)
        vlm = Qwen2_5_VLForConditionalGeneration.from_pretrained(model, torch_dtype=torch.bfloat16)
        vlm = vlm.to("cuda" if torch.cuda.is_available() else "cpu")

        image_pil = _container_to_pil(container)
        buf = io.BytesIO()
        image_pil.save(buf, format="PNG")
        buf.seek(0)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": buf},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        seeds = [seed] if seed is not None else [random.randint(0, 2**31 - 1) for _ in range(n)]
        candidates: list[Candidate] = []

        for s in seeds:
            torch.manual_seed(s)
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = processor(text=[text], images=[image_pil], return_tensors="pt").to(vlm.device)
            output_ids = vlm.generate(**inputs, max_new_tokens=512)
            # Qwen returns a text description; for image editing we need diffusers fallback.
            # This path is suitable for instruction-based region description tasks.
            raise NotImplementedError(
                "Qwen2.5-VL produces text, not pixels. "
                "Use it as a prompt refiner, not a direct image editor."
            )

        return candidates
