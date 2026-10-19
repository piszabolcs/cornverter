"""
Word documents (.docx / .docm) to PDF without LibreOffice.

The fallback of office.py. A .docx/.docm is a ZIP whose `word/document.xml`
holds the text: paragraphs and table cells are read in document order and
typeset into a plain, clean PDF.

Formatting (styles, images, headers/footers) is lost - the point is that the
CONTENT stays a searchable PDF even without LibreOffice.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..fonts import font_set
from .base import ConversionResult, Status, long_path, xml_escape

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Paragraph styles typeset larger and bold (English and Hungarian Word names).
_HEADING_PREFIXES = ("Heading", "Cimsor", "Címsor", "Title")


def _tag(elem) -> str:
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def _paragraph_text(p) -> str:
    """Plain text of a w:p paragraph (with tabs and line breaks)."""
    parts: list[str] = []
    for node in p.iter():
        name = _tag(node)
        if name == "t":
            parts.append(node.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
    return "".join(parts)


def _paragraph_style_name(p) -> str:
    ppr = p.find(f"{_W}pPr")
    style = ppr.find(f"{_W}pStyle") if ppr is not None else None
    return (style.get(f"{_W}val", "") or "") if style is not None else ""


def _table_rows(tbl) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{_W}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{_W}tc"):
            texts = [_paragraph_text(p) for p in tc.findall(f"{_W}p")]
            cells.append("\n".join(t for t in texts if t).strip())
        if cells:
            rows.append(cells)
    return rows


def _read_document_xml(path: Path) -> bytes:
    with zipfile.ZipFile(long_path(path)) as z:
        try:
            return z.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("There is no word/document.xml in the file - "
                             "it is probably not a Word document.") from exc


def _to_markup(text: str) -> str:
    """Line breaks and tabs as reportlab markup."""
    return xml_escape(text).replace("\t", "&nbsp;" * 4).replace("\n", "<br/>")


def _table(rows: list[list[str]], cell_style) -> Table:
    cols = max(len(r) for r in rows)
    data = [[Paragraph(_to_markup(c), cell_style)
             for c in (row + [""] * (cols - len(row)))] for row in rows]
    table = Table(data, colWidths=[(A4[0] - 30 * mm) / cols] * cols)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDE6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    try:
        body = ET.fromstring(_read_document_xml(path)).find(f"{_W}body")
        if body is None:
            raise ValueError("The document body (w:body) is missing.")

        fs = font_set()
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "wmTitle", parent=styles["Title"], fontName=fs.sans_bold,
            fontSize=12, leading=15, alignment=0, spaceAfter=6)
        heading_style = ParagraphStyle(
            "wmHeading", parent=styles["Normal"], fontName=fs.sans_bold,
            fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
        body_style = ParagraphStyle(
            "wmBody", parent=styles["Normal"], fontName=fs.sans,
            fontSize=9.5, leading=13, spaceAfter=4)
        cell_style = ParagraphStyle(
            "wmCell", parent=styles["Normal"], fontName=fs.sans,
            fontSize=8, leading=10)

        story: list = [Paragraph(xml_escape(path.name), title_style)]
        paragraphs = tables = 0
        for child in body:
            name = _tag(child)
            if name == "p":
                text = _paragraph_text(child)
                if not text.strip():
                    story.append(Spacer(1, 3 * mm))
                    continue
                is_heading = _paragraph_style_name(child).startswith(
                    _HEADING_PREFIXES)
                story.append(Paragraph(
                    _to_markup(text),
                    heading_style if is_heading else body_style))
                paragraphs += 1
            elif name == "tbl":
                rows = _table_rows(child)
                if rows:
                    story += [Spacer(1, 2 * mm), _table(rows, cell_style),
                              Spacer(1, 3 * mm)]
                    tables += 1

        if paragraphs == 0 and tables == 0:
            return ConversionResult(
                source=path, status=Status.SKIPPED,
                message="The Word document contains no text.",
                engine="wordml", duration_s=time.time() - start,
            )

        Path(long_path(out_pdf)).parent.mkdir(parents=True, exist_ok=True)
        SimpleDocTemplate(
            str(long_path(out_pdf)), pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=path.name,
        ).build(story)

        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine="wordml+reportlab", duration_s=time.time() - start,
            message=f"{paragraphs} paragraph(s), {tables} table(s), without "
                    f"LibreOffice (content without formatting).",
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"Word to PDF failed: {exc}",
            engine="wordml", duration_s=time.time() - start,
        )
