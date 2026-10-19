"""
RTF documents to PDF without LibreOffice.

The fallback of office.py. RTF is a text format with the content scattered
between braces and `\\control` words; these are stripped and the remaining
text is typeset into a clean PDF.

Formatting, table structure and embedded images are lost - the point is that
the TEXT stays a searchable PDF even without LibreOffice. Faithful layout
needs LibreOffice.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from ..fonts import font_set
from .base import ConversionResult, Status, long_path, xml_escape

# Binary/structural groups whose CONTENT is dropped too (it is not text).
_DROP_GROUPS = (
    "fonttbl", "colortbl", "stylesheet", "listtable", "listoverridetable",
    "info", "pict", "object", "themedata", "colorschememapping",
    "latentstyles", "datastore", "generator", "xmlnstbl", "rsidtbl",
    "mmathPr", "wgrffmtfilter", "filetbl", "revtbl", "upr",
)

# Control words that mean a line break.
_BREAKS = ("par", "line", "sect", "page", "row", "cell", "tab")

_CONTROL_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?")
_HEX_RE = re.compile(r"\\'([0-9a-fA-F]{2})")


def _unicode_char(code: int) -> str:
    if code < 0:              # RTF may write a signed 16-bit value
        code += 65536
    try:
        return chr(code)
    except ValueError:
        return ""


def _codepage(raw: str) -> str:
    """The code page declared in the RTF header (cp1250 for Central Europe)."""
    m = re.search(r"\\ansicpg(\d+)", raw)
    if m:
        try:
            codec = "cp" + m.group(1)
            "x".encode(codec)
            return codec
        except LookupError:
            pass
    return "cp1252"


def rtf_to_text(raw: str) -> str:
    """Plain text of an RTF document, split into paragraphs.

    Escapes (\\uNNNN unicode and \\'hh bytes) are resolved while reading, not
    afterwards: the replacement character after a `\\u225?` must be dropped,
    which can only be done correctly in reading order.
    """
    codepage = _codepage(raw)
    out: list[str] = []
    depth = 0
    # The brace depth where a dropped group started (None: not dropping).
    skip_from: int | None = None
    # \ucN: characters to drop after a \uNNNN (default 1).
    uc = 1
    i = 0
    n = len(raw)

    while i < n:
        ch = raw[i]

        if ch == "\\":
            nxt = raw[i + 1] if i + 1 < n else ""

            # An escaped brace or backslash.
            if nxt in ("\\", "{", "}"):
                if skip_from is None:
                    out.append(nxt)
                i += 2
                continue

            # \'hh - one byte in the document's code page.
            if nxt == "'":
                m = _HEX_RE.match(raw, i)
                if m:
                    if skip_from is None:
                        out.append(bytes([int(m.group(1), 16)])
                                   .decode(codepage, errors="replace"))
                    i = m.end()
                    continue
                i += 2
                continue

            m = _CONTROL_RE.match(raw, i)
            if m:
                word, arg = m.group(1), m.group(2)
                i = m.end()

                if word == "uc":
                    uc = int(arg) if arg is not None else 1
                    continue
                if word == "u" and arg is not None:
                    if skip_from is None:
                        out.append(_unicode_char(int(arg)))
                    # Drop the replacement character(s) after \uNNNN,
                    # otherwise "?" shows up instead of the accent.
                    skipped = 0
                    while skipped < uc and i < n:
                        if raw[i] == "\\" and raw[i:i + 2] == "\\'":
                            hm = _HEX_RE.match(raw, i)
                            i = hm.end() if hm else i + 2
                        else:
                            i += 1
                        skipped += 1
                    continue
                if word in _DROP_GROUPS:
                    # Only the OUTERMOST dropped level counts - see below.
                    if skip_from is None:
                        skip_from = depth
                    continue
                if skip_from is None and word in _BREAKS:
                    out.append("\t" if word == "tab" else "\n")
                continue

            # Non-word controls: \* drops its group, \~ is a non-breaking space.
            if nxt == "*":
                # Word writes a {\*\panose ...} or {\*\falt ...} subgroup into
                # every font entry INSIDE `\fonttbl`. Overwriting the skip level
                # with the deeper value would end the whole fonttbl skip when
                # the subgroup closes, leaking font names into the text. So a
                # skip already running is left alone.
                if skip_from is None:
                    skip_from = depth
                i += 2
                continue
            if nxt == "~":
                if skip_from is None:
                    out.append(" ")
                i += 2
                continue
            i += 2
            continue

        if ch == "{":
            depth += 1
            i += 1
            continue

        if ch == "}":
            depth -= 1
            # A dropped group ends only when the depth falls BELOW its own
            # level. `<=` here was a long-standing bug: a real `\fonttbl` has
            # one `{...}` per font, and the first inner `}` switched the text
            # collection back on - leaking "Times New Roman;Arial;..." into
            # the finished PDF.
            if skip_from is not None and depth < skip_from:
                skip_from = None
            i += 1
            continue

        if ch in "\r\n":
            i += 1
            continue

        if skip_from is None:
            out.append(ch)
        i += 1

    text = "".join(out)
    # Collapse runs of line breaks to one or two.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _read(path: Path) -> str:
    data = Path(long_path(path)).read_bytes()
    for enc in ("utf-8", "cp1250", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    try:
        raw = _read(path)
        if "\\rtf" not in raw[:512]:
            raise ValueError("Not an RTF file (no \\rtf mark in the header).")

        text = rtf_to_text(raw)
        if not text.strip():
            return ConversionResult(
                source=path, status=Status.SKIPPED,
                message="The RTF has no extractable text (probably only an "
                        "image) - this needs LibreOffice.",
                engine="rtftext", duration_s=time.time() - start,
            )

        fs = font_set()
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "rtTitle", parent=styles["Title"], fontName=fs.sans_bold,
            fontSize=12, leading=15, alignment=0, spaceAfter=6)
        body_style = ParagraphStyle(
            "rtBody", parent=styles["Normal"], fontName=fs.sans,
            fontSize=9.5, leading=13, spaceAfter=4)

        story: list = [Paragraph(xml_escape(path.name), title_style),
                       Spacer(1, 2 * mm)]
        paragraphs = 0
        for block in text.split("\n"):
            if not block.strip():
                story.append(Spacer(1, 2.5 * mm))
                continue
            story.append(Paragraph(
                xml_escape(block).replace("\t", "&nbsp;" * 4), body_style))
            paragraphs += 1

        Path(long_path(out_pdf)).parent.mkdir(parents=True, exist_ok=True)
        SimpleDocTemplate(
            str(long_path(out_pdf)), pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=path.name,
        ).build(story)

        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine="rtftext+reportlab", duration_s=time.time() - start,
            message=f"{paragraphs} paragraph(s), without LibreOffice (text "
                    f"without formatting).",
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"RTF to PDF failed: {exc}",
            engine="rtftext", duration_s=time.time() - start,
        )
