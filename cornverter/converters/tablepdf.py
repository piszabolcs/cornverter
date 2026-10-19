"""
Shared table renderer for the reportlab-based converters.

CSV/TSV files (text.py) and spreadsheets (sheet.py) look the same in the
finished PDF: a title, then one table with a header row per section, with
wrapped cells. That code lives here, once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..fonts import font_set
from .base import xml_escape

# From this many columns on the page turns to landscape, otherwise the cells
# get squeezed beyond reading.
_LANDSCAPE_MIN_COLS = 7

# More columns than this do not fit a page usefully: the rest is cut and the
# PDF says so.
MAX_COLS = 40


@dataclass
class Section:
    """One table section: optional heading + rows of cells."""

    heading: str
    rows: list[list[str]]
    note: str = ""


def _clip_columns(rows: list[list[str]]) -> tuple[list[list[str]], int]:
    """Cut rows to MAX_COLS; returns the number of columns cut off."""
    widest = max((len(r) for r in rows), default=0)
    if widest <= MAX_COLS:
        return rows, 0
    return [r[:MAX_COLS] for r in rows], widest - MAX_COLS


def render(out_pdf: Path, title: str, sections: list[Section],
           first_row_is_header: bool = True) -> None:
    """Write the sections into one PDF."""
    fs = font_set()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "cvTitle", parent=styles["Title"], fontName=fs.sans_bold,
        fontSize=12, leading=15, alignment=0,
    )
    heading_style = ParagraphStyle(
        "cvHeading", parent=styles["Normal"], fontName=fs.sans_bold,
        fontSize=10, leading=13, spaceBefore=2, spaceAfter=3,
        textColor=colors.HexColor("#333333"),
    )
    note_style = ParagraphStyle(
        "cvNote", parent=styles["Normal"], fontName=fs.sans,
        fontSize=7.5, leading=10, textColor=colors.HexColor("#777777"),
    )
    header_cell = ParagraphStyle(
        "cvHdrCell", parent=styles["Normal"], fontName=fs.sans_bold,
        fontSize=7, leading=8.5, textColor=colors.white,
    )
    body_cell = ParagraphStyle(
        "cvCell", parent=styles["Normal"], fontName=fs.sans,
        fontSize=7, leading=8.5,
    )

    # The widest section decides the orientation, so the page size does not
    # change within one file.
    widest = max((len(r) for s in sections for r in s.rows), default=0)
    pagesize = landscape(A4) if widest >= _LANDSCAPE_MIN_COLS else A4

    doc = SimpleDocTemplate(
        str(out_pdf), pagesize=pagesize,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=title,
    )

    story: list = [Paragraph(xml_escape(title), title_style),
                   Spacer(1, 4 * mm)]

    for idx, section in enumerate(sections):
        if idx:
            story.append(PageBreak())
        if section.heading:
            story.append(Paragraph(xml_escape(section.heading), heading_style))

        rows, clipped = _clip_columns(section.rows or [["(empty)"]])
        cols = max((len(r) for r in rows), default=1)

        notes = [n for n in (section.note,) if n]
        if clipped:
            notes.append(f"{clipped} more column(s) not shown "
                         f"(max. {MAX_COLS}).")
        for n in notes:
            story.append(Paragraph(xml_escape(n), note_style))
            story.append(Spacer(1, 1.5 * mm))

        data = []
        for r_i, row in enumerate(rows):
            style = header_cell if (first_row_is_header and r_i == 0) \
                else body_cell
            padded = list(row) + [""] * (cols - len(row))
            data.append([Paragraph(xml_escape(c), style) for c in padded])

        col_w = (pagesize[0] - 24 * mm) / cols
        table = Table(data, colWidths=[col_w] * cols,
                      repeatRows=1 if first_row_is_header else 0)
        cmds = [
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if first_row_is_header:
            cmds += [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A1A1F")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F5F5F0")]),
            ]
        else:
            cmds.append(("ROWBACKGROUNDS", (0, 0), (-1, -1),
                         [colors.white, colors.HexColor("#F5F5F0")]))
        table.setStyle(TableStyle(cmds))
        story.append(table)

    doc.build(story)
