from __future__ import annotations

from pathlib import Path

import numpy as np

from .container import ImageContainer

_TIFF_SUFFIXES = {".tif", ".tiff"}
_NO_ALPHA_SUFFIXES = {".jpg", ".jpeg", ".bmp"}


def save(container: ImageContainer, dest: Path | str, fmt: str | None = None) -> Path:
    dest = Path(dest)
    if dest.resolve() == container.source_path.resolve():
        raise ValueError(f"Cannot overwrite source: {dest}")

    from PIL import Image

    pixels = container.pixels
    suffix = dest.suffix.lower()

    if pixels.dtype == np.uint16:
        if suffix not in _TIFF_SUFFIXES:
            raise ValueError(
                f"16-bit images require a TIFF destination (.tif/.tiff); got {dest.suffix!r}"
            )
        if pixels.ndim == 2:
            img = Image.fromarray(pixels.astype(np.int32), "I")
        else:
            # IO-B4: Pillow has no 16-bit-per-channel RGB mode — Image.fromarray raises
            # TypeError on a uint16 HxWx3 array. tifffile writes a true 16-bit
            # multichannel TIFF (this is the only destination the guard above permits).
            import tifffile

            dest.parent.mkdir(parents=True, exist_ok=True)
            tifffile.imwrite(str(dest), pixels)
            return dest
    else:
        if pixels.ndim == 2:
            mode = "L"
        elif pixels.shape[2] == 4:
            mode = "RGBA"
        else:
            mode = "RGB"
        img = Image.fromarray(pixels.astype(np.uint8) if pixels.dtype != np.uint8 else pixels, mode)

    if img.mode == "RGBA" and suffix in _NO_ALPHA_SUFFIXES:
        img = img.convert("RGB")

    dest.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {}
    if container.icc_profile:
        kwargs["icc_profile"] = container.icc_profile

    img.save(dest, format=fmt, **kwargs)
    return dest
