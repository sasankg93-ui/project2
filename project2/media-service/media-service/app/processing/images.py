import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .errors import ProcessingError

log = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
THUMB_SIZE = 320

Output = tuple[Path, str]


def _resize(im: Image.Image, w: int | None, h: int | None) -> Image.Image:
    if w and h:  # exact box: scale then center-crop
        return ImageOps.fit(im, (w, h), Image.LANCZOS)
    out = im.copy()
    if w or h:  # keep aspect ratio, never upscale
        out.thumbnail((w or im.width, h or im.height), Image.LANCZOS)
    return out


def _watermark(im: Image.Image, text: str, font_path: str) -> Image.Image:
    im = im.convert("RGBA")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    size = max(12, im.width // 28)
    try:
        font = ImageFont.truetype(font_path, size)
    except OSError:
        font = ImageFont.load_default(size=size)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    margin = size // 2
    pos = (im.width - (right - left) - margin - left, im.height - (bottom - top) - margin - top)
    draw.text((pos[0] + 1, pos[1] + 1), text, font=font, fill=(0, 0, 0, 110))  # shadow
    draw.text(pos, text, font=font, fill=(255, 255, 255, 170))
    return Image.alpha_composite(im, overlay)


def _for_webp(im: Image.Image) -> Image.Image:
    return im.convert("RGBA" if im.has_transparency_data else "RGB")


def process_image(src: Path, out_dir: Path, opts: dict, s) -> list[Output]:
    """Validate, orient, crop/resize, watermark, and write image.webp + thumb.webp.

    EXIF/metadata (including GPS) is dropped because we never copy it to the output.
    """
    Image.MAX_IMAGE_PIXELS = s.max_image_pixels  # decompression-bomb guard
    w, h = opts.get("width"), opts.get("height")
    quality = int(opts.get("quality", 82))

    try:
        with Image.open(src) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise ProcessingError("Unsupported image format")
            probe.verify()  # cheap integrity check; invalidates the handle

        with Image.open(src) as im:
            if im.format == "JPEG" and (w or h):
                im.draft("RGB", (w or im.width, h or im.height))  # decode at reduced scale
            im = ImageOps.exif_transpose(im)
            im.load()
            main = _resize(im, w, h)
    except ProcessingError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as e:
        raise ProcessingError("Invalid or corrupt image") from e

    if opts.get("watermark") and s.watermark_text:
        main = _watermark(main, s.watermark_text, s.watermark_font_path)
    main = _for_webp(main)

    thumb = main.copy()
    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)

    main_path, thumb_path = out_dir / "image.webp", out_dir / "thumb.webp"
    main.save(main_path, "WEBP", quality=quality, method=4)
    thumb.save(thumb_path, "WEBP", quality=75, method=4)
    return [(main_path, "image/webp"), (thumb_path, "image/webp")]
