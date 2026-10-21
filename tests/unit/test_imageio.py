from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image, ImageCms

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.imageio.savers import save


def _make_rgb_png(path: Path, size: tuple[int, int] = (32, 32)) -> np.ndarray:
    pixels = np.arange(size[0] * size[1] * 3, dtype=np.uint8).reshape(*size, 3)
    Image.fromarray(pixels, "RGB").save(path, format="PNG")
    return pixels


def _make_rgb_jpg(path: Path, size: tuple[int, int] = (32, 32)) -> np.ndarray:
    pixels = np.full((*size, 3), 128, dtype=np.uint8)
    Image.fromarray(pixels, "RGB").save(path, format="JPEG", quality=95)
    return pixels


def test_png_round_trip_pixel_exact(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    original = _make_rgb_png(src)

    container = load(src)
    assert container.bit_depth == 8
    assert container.source_path == src
    np.testing.assert_array_equal(container.pixels, original)

    dest = tmp_path / "output.png"
    save(container, dest)
    loaded2 = load(dest)
    np.testing.assert_array_equal(loaded2.pixels, container.pixels)


def test_jpg_round_trip_shape(tmp_path: Path) -> None:
    src = tmp_path / "source.jpg"
    _make_rgb_jpg(src)

    container = load(src)
    assert container.bit_depth == 8
    assert container.pixels.shape == (32, 32, 3)

    dest = tmp_path / "output.jpg"
    save(container, dest)
    loaded2 = load(dest)
    assert loaded2.pixels.shape == container.pixels.shape


def test_save_raises_on_source_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    _make_rgb_png(src)
    container = load(src)
    with pytest.raises(ValueError, match="overwrite source"):
        save(container, container.source_path)


def test_icc_profile_preserved(tmp_path: Path) -> None:
    srgb = ImageCms.createProfile("sRGB")
    srgb_bytes = ImageCms.ImageCmsProfile(srgb).tobytes()

    img = Image.new("RGB", (32, 32), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG", icc_profile=srgb_bytes)
    src = tmp_path / "icc_test.png"
    src.write_bytes(buf.getvalue())

    container = load(src)
    assert container.icc_profile == srgb_bytes

    dest = tmp_path / "icc_out.png"
    save(container, dest)
    loaded2 = load(dest)
    assert loaded2.icc_profile == srgb_bytes


def _srgb_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _raw_mock(pixels: np.ndarray, thumb) -> MagicMock:
    mock_cm = MagicMock()
    raw = mock_cm.__enter__.return_value
    raw.postprocess.return_value = pixels
    raw.extract_thumb.return_value = thumb
    return mock_cm


def test_raw_16bit_loader() -> None:
    """T5 + IO-D2: _load_raw builds a 16-bit sRGB-tagged container carrying preview EXIF."""
    import rawpy

    pixels = np.ones((10, 10, 3), dtype=np.uint16) * 32768
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="JPEG", exif=exif.tobytes())
    thumb = MagicMock(format=rawpy.ThumbFormat.JPEG, data=buf.getvalue())

    with patch("rawpy.imread", return_value=_raw_mock(pixels, thumb)):
        container = load(Path("fake.nef"))
    assert container.bit_depth == 16
    assert container.pixels.dtype == np.uint16
    np.testing.assert_array_equal(container.pixels, pixels)
    assert container.icc_profile == _srgb_bytes()
    loaded = Image.Exif()
    loaded.load(container.metadata["exif"])
    assert loaded[0x010F] == "TestCam"


@pytest.mark.parametrize(
    "thumb_error",
    [True, False],
    ids=["no_thumbnail", "bitmap_thumbnail"],
)
def test_raw_loader_without_usable_preview_has_icc_but_no_exif(thumb_error: bool) -> None:
    import rawpy

    pixels = np.zeros((4, 4, 3), dtype=np.uint16)
    mock_cm = _raw_mock(pixels, MagicMock(format=rawpy.ThumbFormat.BITMAP))
    if thumb_error:
        mock_cm.__enter__.return_value.extract_thumb.side_effect = rawpy.LibRawNoThumbnailError()
    with patch("rawpy.imread", return_value=mock_cm):
        container = load(Path("fake.nef"))
    assert container.icc_profile == _srgb_bytes()
    assert container.metadata == {}


@pytest.mark.parametrize(
    ("dtype", "bit_depth", "ok"),
    [
        (np.uint8, 8, True),
        (np.uint16, 16, True),
        (np.uint8, 16, False),
        (np.uint16, 8, False),
        (np.float32, 8, False),
        (np.uint8, 12, False),
    ],
)
def test_container_bit_depth_must_match_dtype(dtype, bit_depth: int, ok: bool) -> None:
    """IO-B3: bit_depth is authoritative; construction and copy() reject a mismatch."""
    pixels = np.zeros((2, 2, 3), dtype=dtype)
    if ok:
        c = ImageContainer(pixels=pixels, bit_depth=bit_depth, source_path=Path("x.png"))
        assert c.copy().bit_depth == bit_depth
    else:
        with pytest.raises(ValueError, match="bit_depth"):
            ImageContainer(pixels=pixels, bit_depth=bit_depth, source_path=Path("x.png"))


def test_pil_loader_closes_opened_image(tmp_path: Path) -> None:
    """IO-D1: `_load_pil` releases the Image it opened via a context manager.

    Pillow 12 already drops the fp inside ``load()`` for single-path opens, so the
    observable contract is the ``with`` exit, not the fp state.
    """
    from PIL import ImageFile

    src = tmp_path / "source.png"
    _make_rgb_png(src)
    exited: list[str | None] = []
    real_exit = ImageFile.ImageFile.__exit__

    def _spy(self, *args):
        exited.append(self.format)
        return real_exit(self, *args)

    with patch.object(ImageFile.ImageFile, "__exit__", _spy):
        load(src)
    assert exited == ["PNG"]


def test_16bit_jpeg_raises_valueerror(tmp_path: Path) -> None:
    """IO-B1: 16-bit save to JPEG must raise ValueError instead of silently truncating."""
    src = tmp_path / "source.png"
    _make_rgb_png(src)
    base = load(src)
    pixels_16 = base.pixels.astype(np.uint16) * 257
    c16 = ImageContainer(pixels=pixels_16, bit_depth=16, source_path=src)
    with pytest.raises(ValueError, match="TIFF"):
        save(c16, tmp_path / "out.jpg")


@pytest.mark.parametrize("with_icc", [True, False], ids=["icc", "no_icc"])
def test_16bit_rgb_tiff_keeps_icc_profile(tmp_path: Path, with_icc: bool) -> None:
    """The tifffile branch must embed the container's ICC profile, like the Pillow branch."""
    import tifffile
    from PIL import ImageCms

    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes() if with_icc else None
    c16 = ImageContainer(
        pixels=np.full((8, 8, 3), 30000, dtype=np.uint16),
        bit_depth=16,
        source_path=tmp_path / "src.nef",
        icc_profile=icc,
    )
    dest = save(c16, tmp_path / "out.tif")

    with tifffile.TiffFile(str(dest)) as tf:
        tag = tf.pages[0].tags.get(34675)
        written = bytes(tag.value) if tag else None
    assert written == icc


def test_16bit_rgb_tiff_round_trip(tmp_path: Path) -> None:
    """IO-B4: 16-bit RGB save must not raise and must round-trip exactly (tifffile)."""
    import tifffile

    src = tmp_path / "source.nef"
    pixels_16 = (np.arange(8 * 8 * 3, dtype=np.uint16).reshape(8, 8, 3) * 500).astype(np.uint16)
    c16 = ImageContainer(pixels=pixels_16, bit_depth=16, source_path=src)

    dest = tmp_path / "out.tif"
    save(c16, dest)

    back = tifffile.imread(str(dest))
    assert back.dtype == np.uint16
    np.testing.assert_array_equal(back, pixels_16)


def test_exif_orientation_applied_on_load(tmp_path: Path) -> None:
    """IO-B5: EXIF Orientation=6 (rotate 90° CW) must be baked into the pixels on load
    and the tag cleared, so a later save cannot leave the output sideways."""
    src = tmp_path / "portrait.jpg"
    base = Image.fromarray(np.zeros((10, 20, 3), dtype=np.uint8), "RGB")  # 20 wide, 10 tall
    exif = base.getexif()
    exif[274] = 6  # Orientation: rotate 90° CW on display
    base.save(src, format="JPEG", exif=exif)

    container = load(src)
    # Orientation 6 swaps the axes: stored 10x20 -> displayed 20x10.
    assert container.pixels.shape[:2] == (20, 10)

    raw = Image.open(src)
    assert raw.getexif().get(274, 1) == 6  # source file untouched
    assert container.metadata.get("exif") is None or _orientation(container.metadata["exif"]) in (
        None,
        1,
    )


def _orientation(exif_bytes: bytes):
    img = Image.new("RGB", (1, 1))
    ex = img.getexif()
    try:
        ex.load(exif_bytes)
    except Exception:
        return None
    return ex.get(274)


def test_rgba_jpeg_saves_as_rgb(tmp_path: Path) -> None:
    """IO-B2: RGBA container saved to JPEG must not raise; alpha channel is dropped."""
    pixels_rgba = np.full((32, 32, 4), 128, dtype=np.uint8)
    src = tmp_path / "source_rgba.png"
    Image.fromarray(pixels_rgba, "RGBA").save(src)
    container = ImageContainer(pixels=pixels_rgba, bit_depth=8, source_path=src)
    dest = tmp_path / "out.jpg"
    save(container, dest)
    loaded = load(dest)
    assert loaded.pixels.shape[2] == 3


def _exif_with_thumbnail(thumb: bytes) -> bytes:
    """Raw APP1 EXIF: IFD0 {Make="Cam", Orientation=6} -> IFD1 pointing at a JPEG thumbnail."""
    import struct

    ifd0 = (
        struct.pack("<H", 2)
        + struct.pack("<HHI4s", 0x010F, 2, 4, b"Cam\0")
        + struct.pack("<HHIHH", 0x0112, 3, 1, 6, 0)
        + struct.pack("<I", 38)
    )
    ifd1 = (
        struct.pack("<H", 2)
        + struct.pack("<HHII", 0x0201, 4, 1, 68)
        + struct.pack("<HHII", 0x0202, 4, 1, len(thumb))
        + struct.pack("<I", 0)
    )
    return b"Exif\x00\x00" + b"II*\x00" + struct.pack("<I", 8) + ifd0 + ifd1 + thumb


@pytest.mark.parametrize("suffix", [".jpg", ".png", ".webp", ".tif"])
def test_exif_carried_to_output_without_thumbnail_or_orientation(
    tmp_path: Path, suffix: str
) -> None:
    """IO-D3: capture metadata survives a save; the stale thumbnail and orientation do not."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, format="JPEG")
    thumb = buf.getvalue()
    container = ImageContainer(
        pixels=np.zeros((16, 24, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=tmp_path / "src.jpg",
        metadata={"exif": _exif_with_thumbnail(thumb)},
    )
    dest = save(container, tmp_path / f"out{suffix}")

    written = Image.open(dest).getexif()
    assert written.get(0x010F) == "Cam"
    assert written.get(0x0112) is None
    assert thumb[:32] not in dest.read_bytes()


def test_unreadable_exif_does_not_block_save(tmp_path: Path) -> None:
    container = ImageContainer(
        pixels=np.zeros((8, 8, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=tmp_path / "src.jpg",
        metadata={"exif": b"garbage-not-exif"},
    )
    dest = save(container, tmp_path / "out.jpg")
    assert not Image.open(dest).getexif()


@pytest.mark.parametrize("suffix,fmt", [(".jpg", None), (".jpeg", None), (".out", "JPEG")])
def test_jpeg_saved_high_quality_full_chroma(tmp_path: Path, suffix: str, fmt) -> None:
    from PIL import JpegImagePlugin

    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
    container = ImageContainer(pixels=pixels, bit_depth=8, source_path=tmp_path / "src.png")
    dest = save(container, tmp_path / f"out{suffix}", fmt=fmt)

    written = Image.open(dest)
    assert JpegImagePlugin.get_sampling(written) == 0  # 4:4:4, no chroma subsampling
    assert written.quantization[0][0] <= 3  # quality 95 (Pillow's default 75 gives 8)
