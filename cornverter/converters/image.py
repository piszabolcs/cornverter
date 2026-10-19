"""
Images and scans to PDF.

Handled: .tif, .tiff, .png, .jpg, .jpeg, .bmp, .gif, .webp

There is deliberately NO OCR: the job is to put the image into a PDF, one
image = one page, every frame of a multi-page TIF included. A searchable text
layer can be added to the finished PDF by a dedicated OCR tool.

Two routes, in this order:

  1. **Direct embedding** - img2pdf puts JPEG and (CCITT G4 / LZW) TIF data
     into the PDF WITHOUT re-encoding. Large engineering scans are typically
     like this: a 13242x18723 pixel G4 TIF goes into a PDF in seconds,
     without growing.
  2. **Normalising** - when img2pdf rejects the colour space (CMYK JPEG,
     PNG with alpha or a palette), Pillow converts each frame to RGB first.
     This is the slow, memory-hungry route, so it is only the fallback.

The result is always an image PDF, so no content is lost.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from .base import ConversionResult, Status, long_path

# A4 in points (72 dpi) - images are fitted to it, so pages are neither tiny
# nor larger than the paper.
_A4_PT = (595.28, 841.89)

# Pillow's default "decompression bomb" guard (~179 million pixels) is meant
# for images from the web; an A0 engineering scan alone is ~250 million. The
# guard is raised, not removed: Pillow still refuses images above twice this
# value, so a hostile image (e.g. from an archive or an e-mail) cannot claim
# unlimited memory.
_MAX_IMAGE_PIXELS = 600_000_000
_PIXEL_LIMIT_SET = False

# On the fallback (Pillow) route, larger frames are scaled down, otherwise
# decoding an A0 scan would take hundreds of MB.
_FALLBACK_MAX_PIXELS = 60_000_000


def _set_pixel_limit() -> None:
    global _PIXEL_LIMIT_SET
    if _PIXEL_LIMIT_SET:
        return
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    _PIXEL_LIMIT_SET = True


def _layout():
    import img2pdf

    return img2pdf.get_layout_fun(pagesize=_A4_PT)


def _page_count(pdf: Path) -> int:
    try:
        from pypdf import PdfReader

        with open(long_path(pdf), "rb") as f:
            return len(PdfReader(f).pages)
    except Exception:  # noqa: BLE001
        return 1


def _embed_directly(src: Path, out_pdf: Path) -> bool:
    """Embed the image without re-encoding. Returns success."""
    import img2pdf

    try:
        data = img2pdf.convert(str(long_path(src)), layout_fun=_layout())
    except Exception:  # noqa: BLE001 - unsupported colour space / format
        return False
    with open(long_path(out_pdf), "wb") as f:
        f.write(data)
    return True


def _frames_to_png(src: Path, tmpdir: Path) -> list[str]:
    """Write every frame of the image to its own RGB PNG.

    This normalises CMYK, palette, alpha and multi-page (TIF) images, since
    img2pdf only accepts certain colour spaces.
    """
    from PIL import Image, ImageSequence

    paths: list[str] = []
    with Image.open(long_path(src)) as im:
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            rgb = frame.convert("RGB")
            if rgb.width * rgb.height > _FALLBACK_MAX_PIXELS:
                # Scale down proportionally below the memory limit.
                scale = (_FALLBACK_MAX_PIXELS / (rgb.width * rgb.height)) ** 0.5
                rgb = rgb.resize(
                    (max(int(rgb.width * scale), 1),
                     max(int(rgb.height * scale), 1)),
                    Image.LANCZOS,
                )
            fp = tmpdir / f"page_{i:04d}.png"
            rgb.save(fp)
            paths.append(str(fp))
    if not paths:
        raise ValueError("The image has no frame to convert.")
    return paths


def _normalize_and_embed(src: Path, out_pdf: Path) -> None:
    """Normalise to RGB with Pillow, then embed."""
    import img2pdf

    tmpdir = Path(tempfile.mkdtemp(prefix="cv_img_"))
    try:
        frames = _frames_to_png(src, tmpdir)
        with open(long_path(out_pdf), "wb") as f:
            f.write(img2pdf.convert(frames, layout_fun=_layout()))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    _set_pixel_limit()
    Path(long_path(out_pdf)).parent.mkdir(parents=True, exist_ok=True)

    try:
        if _embed_directly(path, out_pdf):
            engine, note = "img2pdf", ""
        else:
            _normalize_and_embed(path, out_pdf)
            engine, note = "img2pdf+pillow", "Colour space normalised (RGB)."

        pages = _page_count(out_pdf)
        if pages > 1:
            note = f"{note} {pages}-page image PDF.".strip()
        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine=engine, duration_s=time.time() - start, message=note,
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"Image to PDF failed: {exc}",
            engine="img2pdf", duration_s=time.time() - start,
        )
