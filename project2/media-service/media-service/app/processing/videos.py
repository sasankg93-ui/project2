import logging
import subprocess
from pathlib import Path

import ffmpeg

from .errors import ProcessingError

log = logging.getLogger(__name__)

Output = tuple[Path, str]


def _probe(src: Path) -> dict:
    try:
        return ffmpeg.probe(str(src))
    except ffmpeg.Error as e:
        log.warning("ffprobe failed: %s", (e.stderr or b"").decode(errors="replace")[-500:])
        raise ProcessingError("Invalid or unreadable video") from e


def _run(spec, timeout: int, what: str) -> None:
    # run_async + communicate(timeout) lets us kill ffmpeg itself on timeout.
    proc = ffmpeg.run_async(spec, pipe_stdout=True, pipe_stderr=True, overwrite_output=True)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise ProcessingError(f"{what} timed out")
    if proc.returncode != 0:
        log.warning("ffmpeg %s failed: %s", what, (err or b"").decode(errors="replace")[-800:])
        raise ProcessingError(f"Could not {what}")


def process_video(src: Path, out_dir: Path, opts: dict, s) -> list[Output]:
    """Transcode to web-optimized MP4 (H.264 + AAC, faststart) and extract a JPEG thumbnail."""
    info = _probe(src)
    streams = info.get("streams", [])
    vstream = next((x for x in streams if x.get("codec_type") == "video"), None)
    if vstream is None:
        raise ProcessingError("File has no video stream")
    has_audio = any(x.get("codec_type") == "audio" for x in streams)

    duration = float(info.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ProcessingError("Could not determine video duration")
    if duration > s.max_video_seconds:
        raise ProcessingError(f"Video longer than {s.max_video_seconds // 60} minutes")
    src_h = int(vstream.get("height") or 0)
    if src_h <= 0:
        raise ProcessingError("Could not determine video size")

    # Never upscale; keep height even (required by yuv420p / H.264).
    target_h = min(int(opts.get("max_height", 720)), src_h)
    target_h -= target_h % 2

    mp4, thumb = out_dir / "video.mp4", out_dir / "thumb.jpg"

    inp = ffmpeg.input(str(src))
    v = inp.video.filter("scale", -2, target_h)
    if opts.get("watermark") and s.watermark_text:
        v = v.drawtext(
            text=s.watermark_text, fontfile=s.watermark_font_path, fontsize=24,
            fontcolor="white@0.7", x="w-tw-20", y="h-th-20",
            box=1, boxcolor="black@0.3", boxborderw=6,
        )
    common = dict(
        vcodec="libx264", crf=23, preset="veryfast", pix_fmt="yuv420p",
        movflags="+faststart", threads=s.ffmpeg_threads, **{"profile:v": "high"},
    )
    if has_audio:
        out = ffmpeg.output(v, inp.audio, str(mp4), acodec="aac", audio_bitrate="128k", **common)
    else:
        out = ffmpeg.output(v, str(mp4), **common)
    _run(out.global_args("-nostdin"), s.ffmpeg_timeout_seconds, "transcode video")

    # Thumbnail from ~1s in (or the midpoint of very short clips).
    t = min(1.0, duration / 2)
    th = (
        ffmpeg.input(str(src), ss=t)
        .filter("scale", 640, -2)
        .output(str(thumb), vframes=1, **{"q:v": 3})
        .global_args("-nostdin")
    )
    _run(th, 60, "extract thumbnail")

    return [(mp4, "video/mp4"), (thumb, "image/jpeg")]
