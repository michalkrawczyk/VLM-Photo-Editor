from __future__ import annotations

import functools
import io
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


@functools.lru_cache(maxsize=1)
def _srgb_icc() -> bytes:
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _raw_exif(raw) -> bytes | None:
    """EXIF from the RAW's embedded JPEG preview, or None.

    rawpy exposes no EXIF accessor; the preview JPEG most cameras embed carries it.
    """
    import rawpy
    from PIL import Image

    try:
        thumb = raw.extract_thumb()
    except rawpy.LibRawError:  # no/unsupported thumbnail (e.g. some DNGs)
        return None
    if thumb.format != rawpy.ThumbFormat.JPEG:
        return None
    try:
        with Image.open(io.BytesIO(thumb.data)) as preview:
            exif = preview.info.get("exif")
    except OSError:
        return None
    return exif if isinstance(exif, bytes) and exif else None


def _load_raw(path: Path) -> ImageContainer:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            output_bps=16,
            output_color=rawpy.ColorSpace.sRGB,
            use_camera_wb=True,
            no_auto_bright=True,
        )
        exif = _raw_exif(raw)
    # rgb: uint16 HxWx3, developed into sRGB (IO-D2: tag it so downstream stays honest)
    return ImageContainer(
        pixels=rgb,
        bit_depth=16,
        source_path=path,
        icc_profile=_srgb_icc(),
        metadata={"exif": exif} if exif else {},
    )


def _load_pil(path: Path) -> ImageContainer:
    from PIL import Image, ImageOps

    # IO-D1: close the file handle deterministically; batch runs open hundreds of images.
    with Image.open(path) as opened:
        opened.load()

        # IO-B5: rotate pixels to display orientation and drop the EXIF Orientation tag.
        # Without this, portrait photos are edited/exported sideways (the tag is not written
        # on save) and detection/planner reason about geometry on rotated pixels.
        img = ImageOps.exif_transpose(opened)

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
