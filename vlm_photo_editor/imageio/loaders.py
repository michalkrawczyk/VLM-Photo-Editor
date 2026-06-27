from __future__ import annotations

from pathlib import Path

import numpy as np

from .container import ImageContainer

RAW_EXTENSIONS = {".nef", ".cr2", ".cr3", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw"}
PIL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
assert not (RAW_EXTENSIONS & PIL_EXTENSIONS), "Extension sets overlap"


def load(path: Path | str) -> ImageContainer:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in RAW_EXTENSIONS:
        return _load_raw(path)
    if suffix in PIL_EXTENSIONS:
        return _load_pil(path)
    raise ValueError(f"Unsupported format: {suffix!r}")


def _load_raw(path: Path) -> ImageContainer:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            output_bps=16,
            use_camera_wb=True,
            no_auto_bright=True,
        )
    # rgb: uint16 HxWx3
    return ImageContainer(
        pixels=rgb,
        bit_depth=16,
        source_path=path,
        icc_profile=None,
        metadata={},
    )


def _load_pil(path: Path) -> ImageContainer:
    from PIL import Image

    img = Image.open(path)
    img.load()

    icc = img.info.get("icc_profile")
    metadata = {k: v for k, v in img.info.items() if k != "icc_profile"}

    # Ensure RGB
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    pixels = np.array(img)
    bit_depth = 16 if pixels.dtype == np.uint16 else 8

    return ImageContainer(
        pixels=pixels,
        bit_depth=bit_depth,
        source_path=path,
        icc_profile=icc if isinstance(icc, bytes) else None,
        metadata=metadata,
    )
