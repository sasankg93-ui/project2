import pytest
from PIL import Image

from app.processing.errors import ProcessingError
from app.processing.images import process_image


@pytest.fixture
def jpeg(tmp_path):
    p = tmp_path / "in"
    Image.new("RGB", (4000, 3000), (200, 30, 30)).save(p, "JPEG")
    return p


def run(src, tmp_path, settings, **opts):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return process_image(src, out, opts, settings)


def test_resize_keeps_aspect(jpeg, tmp_path, settings):
    (main, _), (thumb, _) = run(jpeg, tmp_path, settings, width=800)
    assert Image.open(main).size == (800, 600)
    assert max(Image.open(thumb).size) <= 320


def test_exact_crop(jpeg, tmp_path, settings):
    (main, _), _ = run(jpeg, tmp_path, settings, width=500, height=500)
    assert Image.open(main).size == (500, 500)


def test_never_upscales(jpeg, tmp_path, settings):
    (main, _), _ = run(jpeg, tmp_path, settings, width=8000)
    assert Image.open(main).size == (4000, 3000)


def test_watermark_changes_pixels(jpeg, tmp_path, settings):
    (plain, _), _ = run(jpeg, tmp_path, settings, width=800)
    before = Image.open(plain).convert("RGB").tobytes()
    (marked, _), _ = run(jpeg, tmp_path, settings, width=800, watermark=True)
    assert Image.open(marked).convert("RGB").tobytes() != before


def test_corrupt_file_is_permanent_error(tmp_path, settings):
    bad = tmp_path / "bad"
    bad.write_bytes(b"not an image at all")
    with pytest.raises(ProcessingError):
        run(bad, tmp_path, settings)


def test_decompression_bomb_rejected(jpeg, tmp_path, settings):
    settings.max_image_pixels = 1000
    with pytest.raises(ProcessingError):
        run(jpeg, tmp_path, settings)
