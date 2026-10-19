"""
PowerPoint presentations (.pptx / .pptm) to PDF without LibreOffice.

The fallback of office.py. A .pptx is a ZIP whose `ppt/slides/slideN.xml`
files hold the slide text: one section per slide with the text frames in
order, followed by the speaker notes.

Slide graphics, layout and images are lost - the point is that the TEXT
stays a searchable PDF even without LibreOffice.
"""

from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from ..fonts import font_set
from .base import ConversionResult, Status, long_path, xml_escape

# DrawingML text namespace (the slide text lives here).
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_SLIDE_RE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_NOTES_RE = re.compile(r"ppt/notesSlides/notesSlide(\d+)\.xml$")


def _paragraphs(xml: bytes) -> list[str]:
    """The paragraphs of one slide XML, in order."""
    out: list[str] = []
    for para in ET.fromstring(xml).iter(f"{_A}p"):
        runs: list[str] = []
        for node in para.iter():
            tag = node.tag.split("}")[-1]
            if tag == "t":
                runs.append(node.text or "")
            elif tag == "br":
                runs.append("\n")
        text = "".join(runs).strip()
        if text:
            out.append(text)
    return out


def _numbered(names: list[str], pattern: re.Pattern) -> dict[int, str]:
    found: dict[int, str] = {}
    for name in names:
        m = pattern.search(name)
        if m:
            found[int(m.group(1))] = name
    return found


def _styles():
    fs = font_set()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ppTitle", parent=base["Title"], fontName=fs.sans_bold,
            fontSize=12, leading=15, alignment=0, spaceAfter=6),
        "slide": ParagraphStyle(
            "ppSlide", parent=base["Normal"], fontName=fs.sans_bold,
            fontSize=11, leading=14, spaceBefore=10, spaceAfter=4,
            textColor=colors.HexColor("#333333")),
        "body": ParagraphStyle(
            "ppBody", parent=base["Normal"], fontName=fs.sans,
            fontSize=9.5, leading=13, spaceAfter=3, leftIndent=6),
        "note": ParagraphStyle(
            "ppNote", parent=base["Normal"], fontName=fs.sans,
            fontSize=8.5, leading=11, spaceAfter=2, leftIndent=12,
            textColor=colors.HexColor("#777777")),
    }


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    try:
        with zipfile.ZipFile(long_path(path)) as z:
            names = z.namelist()
            slides = _numbered(names, _SLIDE_RE)
            if not slides:
                raise ValueError("There is no ppt/slides/ content in the file "
                                 "- it is probably not a presentation.")
            notes = _numbered(names, _NOTES_RE)

            st = _styles()
            story: list = [Paragraph(xml_escape(path.name), st["title"])]
            with_text = 0
            for number in sorted(slides):
                lines = _paragraphs(z.read(slides[number]))
                story.append(Paragraph(f"Slide {number}", st["slide"]))
                if lines:
                    with_text += 1
                    story += [Paragraph(xml_escape(line).replace("\n", "<br/>"),
                                        st["body"]) for line in lines]
                else:
                    story.append(Paragraph("(no text on this slide)",
                                           st["note"]))
                note_lines = (_paragraphs(z.read(notes[number]))
                              if number in notes else [])
                if note_lines:
                    story.append(Paragraph("Notes:", st["note"]))
                    story += [Paragraph(xml_escape(line), st["note"])
                              for line in note_lines]
                story.append(Spacer(1, 2 * mm))

        if with_text == 0:
            return ConversionResult(
                source=path, status=Status.SKIPPED,
                message=f"None of the {len(slides)} slide(s) has text (only "
                        f"images/graphics) - this needs LibreOffice.",
                engine="pptxml", duration_s=time.time() - start,
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
            engine="pptxml+reportlab", duration_s=time.time() - start,
            message=f"{len(slides)} slide(s) ({with_text} with text), without "
                    f"LibreOffice (text only).",
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"PowerPoint to PDF failed: {exc}",
            engine="pptxml", duration_s=time.time() - start,
        )
