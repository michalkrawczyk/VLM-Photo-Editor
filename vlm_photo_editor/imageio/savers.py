from __future__ import annotations

from pathlib import Path

import numpy as np

from .container import ImageContainer


def save(container: ImageContainer, dest: Path | str, fmt: str | None = None) -> Path:
    dest = Path(dest)
    if dest.resolve() == container.source_path.resolve():
        raise ValueError(f"Cannot overwrite source: {dest}")

    from PIL import Image

    pixels = container.pixels
    if pixels.ndim == 2:
        mode = "L"
    elif pixels.shape[2] == 4:
        mode = "RGBA"
    else:
        mode = "RGB"

    if pixels.dtype == np.uint16:
        # PIL RGB saves uint16 via mode 'RGB;16' but fromarray needs 'I' for single-channel
        # Simplest: downscale to 8-bit for save (preserves visual fidelity)
        pixels = (pixels >> 8).astype(np.uint8)

    img = Image.fromarray(pixels.astype(np.uint8) if pixels.dtype != np.uint8 else pixels, mode)

    dest.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {}
    if container.icc_profile:
        kwargs["icc_profile"] = container.icc_profile

    img.save(dest, format=fmt, **kwargs)
    return dest
