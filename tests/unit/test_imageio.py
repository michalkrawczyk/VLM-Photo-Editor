from __future__ import annotations

import io
from pathlib import Path

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


@pytest.mark.skipif(
    not Path("tests/fixtures/images/sample.nef").exists(),
    reason="No RAW fixture — skipped",
)
def test_raw_16bit() -> None:
    container = load(Path("tests/fixtures/images/sample.nef"))
    assert container.bit_depth == 16
    assert container.pixels.dtype == np.uint16


def test_16bit_jpeg_raises_valueerror(tmp_path: Path) -> None:
    """IO-B1: 16-bit save to JPEG must raise ValueError instead of silently truncating."""
    src = tmp_path / "source.png"
    _make_rgb_png(src)
    base = load(src)
    pixels_16 = base.pixels.astype(np.uint16) * 257
    c16 = ImageContainer(pixels=pixels_16, bit_depth=16, source_path=src)
    with pytest.raises(ValueError, match="TIFF"):
        save(c16, tmp_path / "out.jpg")


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
