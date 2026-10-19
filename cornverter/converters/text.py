"""
Text and simple table files to PDF.

Handled: .txt, .log, .md, .csv, .tsv

CSV/TSV files are rendered as a table (when the delimiter can be detected),
everything else as a monospaced text block with line wrapping and paging.
The encoding is detected, so accented text does not break.
"""

from __future__ import annotations

import codecs
import csv
import io
import time
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

from ..fonts import font_set
from .base import ConversionResult, Status, xml_escape
from .tablepdf import Section, render

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1250", "latin-1")

# Longer lines are wrapped so they do not run off the page.
_WRAP_AT = 110

# Lines per Preformatted block - this lets reportlab break pages.
_BLOCK_LINES = 60


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    # UTF-16 (Windows "Unicode" text) carries a byte order mark.
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", errors="replace")
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sniff_delimiter(sample: str) -> str | None:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return None


def _convert_table(path: Path, out_pdf: Path, delimiter: str) -> None:
    reader = csv.reader(io.StringIO(_read_text(path)), delimiter=delimiter)
    rows = [[str(c) for c in row] for row in reader] or [["(empty file)"]]
    render(out_pdf, path.name, [Section(heading="", rows=rows)])


def _wrap_lines(text: str) -> list[str]:
    wrapped: list[str] = []
    for line in text.splitlines() or [""]:
        # A tab would shift the line in the monospaced block.
        line = line.replace("\t", "    ")
        if len(line) <= _WRAP_AT:
            wrapped.append(line)
        else:
            wrapped += [line[i:i + _WRAP_AT]
                        for i in range(0, len(line), _WRAP_AT)]
    return wrapped


def _convert_plain(path: Path, out_pdf: Path) -> None:
    fs = font_set()
    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=path.name,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontName=fs.sans_bold,
        fontSize=12, leading=14, alignment=0,
    )
    mono = ParagraphStyle(
        "mono", parent=styles["Code"], fontName=fs.mono,
        fontSize=8, leading=10,
    )

    story = [Paragraph(xml_escape(path.name), title_style), Spacer(1, 4 * mm)]
    lines = _wrap_lines(_read_text(path))
    if not any(line.strip() for line in lines):
        story.append(Preformatted("(empty file)", mono))
    else:
        for i in range(0, len(lines), _BLOCK_LINES):
            story.append(Preformatted("\n".join(lines[i:i + _BLOCK_LINES]),
                                      mono))
    doc.build(story)


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        ext = path.suffix.lower()
        if ext in (".csv", ".tsv"):
            sample = _read_text(path)[:4096]
            delim = "\t" if ext == ".tsv" else (_sniff_delimiter(sample) or ",")
            _convert_table(path, out_pdf, delim)
            engine = "reportlab-table"
        else:
            _convert_plain(path, out_pdf)
            engine = "reportlab-text"
        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine=engine, duration_s=time.time() - start,
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"Text to PDF failed: {exc}",
            engine="reportlab", duration_s=time.time() - start,
        )
