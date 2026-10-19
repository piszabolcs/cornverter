"""
Converter dispatcher: sends one input file to the right module.

`convert_file` is the single entry point - the GUI, the command line and the
converters themselves (e-mail attachments, archive members) all use it. The
sub-modules are imported at call time to avoid circular imports.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .base import ConversionResult, Status, categorize, long_path


@dataclass
class Options:
    """Global conversion settings (set by the GUI or the command line)."""

    convert_msg: bool = True        # .msg / .eml e-mails
    convert_excel: bool = True      # spreadsheets
    convert_images: bool = True     # images (TIF/PNG/JPG...)
    expand_archives: bool = True    # unpack archives
    # PDF / Word / PowerPoint files too: PDFs are copied to the output
    # folder, Word and PowerPoint files are converted.
    convert_accepted: bool = True
    # Overwrite a PDF that already exists at the target path. Off by default:
    # an existing file is never replaced silently.
    overwrite: bool = False


def _copy_pdf(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    try:
        Path(long_path(out_pdf)).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(long_path(path)), str(long_path(out_pdf)))
        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine="copy", duration_s=time.time() - start,
            message="Already a PDF - copied.",
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"Could not copy the PDF: {exc}", engine="copy",
            duration_s=time.time() - start,
        )


def _skipped(path: Path, message: str) -> ConversionResult:
    return ConversionResult(source=path, status=Status.SKIPPED,
                            message=message, engine="dispatch")


def convert_file(path: Path, out_pdf: Path,
                 options: Options | None = None) -> ConversionResult:
    """Convert one file to PDF, chosen by its extension.

    The scan already decides what to leave out; the options are applied here
    as well so that nested calls (attachments, archive members) behave the
    same way.
    """
    opts = options or Options()
    path = Path(path)
    out_pdf = Path(out_pdf)
    cat = categorize(path)

    if cat == "accepted":
        if path.suffix.lower() == ".pdf":
            return _copy_pdf(path, out_pdf)
        # .doc/.docx/.ppt/.pptx: needed as PDF inside attachments and
        # archives, and in the main list when the option is on.
        from . import office
        return office.convert(path, out_pdf)

    if cat == "junk":
        return _skipped(path, "Junk file type - skipped.")

    if cat == "text":
        from . import text
        return text.convert(path, out_pdf)

    if cat == "office":
        from . import office
        return office.convert(path, out_pdf)

    if cat == "msg":
        if not opts.convert_msg:
            return _skipped(path, "E-mail conversion is switched off.")
        from . import msg
        return msg.convert(path, out_pdf)

    if cat == "image":
        from . import image
        return image.convert(path, out_pdf)

    if cat == "archive":
        if not opts.expand_archives:
            return _skipped(path, "Archive unpacking is switched off.")
        from . import archive
        return archive.convert(path, out_pdf)

    return ConversionResult(
        source=path, status=Status.UNSUPPORTED,
        message=f"No converter for {path.suffix or '(no extension)'}",
        engine="dispatch",
    )
