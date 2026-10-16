from __future__ import annotations

import logging
import math

from vlm_photo_editor.schema.report import ExifSummary

logger = logging.getLogger(__name__)

_EXIF_IFD = 0x8769
_ISO, _EXPOSURE_TIME, _F_NUMBER = 0x8827, 0x829A, 0x829D
_EXPOSURE_BIAS, _FOCAL_LENGTH, _WHITE_BALANCE = 0x9204, 0x920A, 0xA403


def _number(value: object) -> float | None:
    try:
        number = float(value)  # IFDRational, int, float
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) else None


def parse_exif(raw: object) -> ExifSummary:
    """Whitelisted EXIF fields from raw EXIF bytes; any failure yields an all-None summary."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return ExifSummary()
    try:
        from PIL import Image

        exif = Image.Exif()
        exif.load(bytes(raw))
        tags = {**exif, **exif.get_ifd(_EXIF_IFD)}
    except Exception as exc:  # corrupt EXIF must never block planning
        logger.debug("EXIF unreadable, ignoring: %s", exc)
        return ExifSummary()

    iso = tags.get(_ISO)
    if isinstance(iso, (tuple, list)):  # some writers store ISO as a sequence
        iso = iso[0] if iso else None
    iso_value = _number(iso)
    wb = tags.get(_WHITE_BALANCE)
    return ExifSummary(
        iso=int(iso_value) if iso_value and iso_value > 0 else None,
        exposure_time_s=_number(tags.get(_EXPOSURE_TIME)),
        f_number=_number(tags.get(_F_NUMBER)),
        focal_length_mm=_number(tags.get(_FOCAL_LENGTH)),
        wb_mode={0: "auto", 1: "manual"}.get(wb) if isinstance(wb, int) else None,
        exposure_bias_ev=_number(tags.get(_EXPOSURE_BIAS)),
    )


__all__ = ["parse_exif"]
