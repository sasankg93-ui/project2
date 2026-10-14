import shutil
import subprocess

import pytest

from app.processing.errors import ProcessingError
from app.processing.videos import process_video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def clip(tmp_path):
    p = tmp_path / "in"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
         "-f", "mp4", str(p)],
        check=True, capture_output=True,
    )
    return p


def test_transcode_and_thumbnail(clip, tmp_path, settings):
    out = tmp_path / "out"
    out.mkdir()
    outputs = process_video(clip, out, {"max_height": 360}, settings)
    names = {p.name for p, _ in outputs}
    assert names == {"video.mp4", "thumb.jpg"}
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
         "-of", "csv=p=0", str(out / "video.mp4")], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "360"


def test_not_a_video(tmp_path, settings):
    bad = tmp_path / "bad"
    bad.write_bytes(b"hello world")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ProcessingError):
        process_video(bad, out, {}, settings)
