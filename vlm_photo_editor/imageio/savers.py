from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .container import ImageContainer

logger = logging.getLogger(__name__)

_TIFF_SUFFIXES = {".tif", ".tiff"}
_NO_ALPHA_SUFFIXES = {".jpg", ".jpeg", ".bmp"}
_JPEG_SUFFIXES = {".jpg", ".jpeg"}


def _exif_bytes(container: ImageContainer) -> bytes | None:
    """Source EXIF re-serialised for the edited file, or None.

    Rebuilt through ``Image.Exif`` rather than copied verbatim: that drops the embedded
    IFD1 thumbnail, which would otherwise show viewers the unedited picture. Orientation
    is already gone (``loaders`` applies it to the pixels), and is popped again in case a
    container was built some other way.
    """
    raw = container.metadata.get("exif")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    try:
        from PIL import Image

        exif = Image.Exif()
        exif.load(bytes(raw))
        exif.pop(0x0112, None)  # Orientation
        return exif.tobytes()
    except Exception as exc:  # corrupt EXIF must not block saving the edit
        logger.warning("Source EXIF unreadable, saving without it: %s", exc)
        return None


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
            tifffile.imwrite(str(dest), pixels, iccprofile=container.icc_profile)
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
    exif = _exif_bytes(container)
    if exif:
        kwargs["exif"] = exif
    is_jpeg = fmt.upper() in ("JPEG", "JPG") if fmt else suffix in _JPEG_SUFFIXES
    if is_jpeg:
        # Pillow defaults to quality 75 with 4:2:0 chroma: visible loss on every export.
        kwargs.update(quality=95, subsampling=0)

    img.save(dest, format=fmt, **kwargs)
    return dest
