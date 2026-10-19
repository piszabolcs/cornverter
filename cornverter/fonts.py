"""
PDF fonts with full Unicode coverage.

reportlab's built-in fonts (Helvetica, Courier) use WinAnsiEncoding, which
lacks characters such as "ő" and "ű" - they come out as black squares in the
finished PDF. So a real TrueType family is registered once, and the
converters use only the names returned here.

Search order:
  1. System fonts (Windows: Arial + Consolas, Linux: DejaVu) - the nicest,
     with full Latin coverage.
  2. Bitstream Vera, shipped with reportlab - always available.
  3. Last resort: the built-in Helvetica/Courier. Some accented characters
     may then be wrong, which `FontSet.unicode_ok` records.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# WinAnsiEncoding fails on these characters - a font is tested with them.
_PROBE = "őűŐŰ"


@dataclass(frozen=True)
class FontSet:
    """The font names the converters use, in one bundle."""

    sans: str
    sans_bold: str
    mono: str
    mono_bold: str
    unicode_ok: bool


# (family, regular file, bold file), in order of preference.
_SANS_CANDIDATES = [
    ("CV-Sans", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ("CV-Sans", r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf"),
    ("CV-Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("CV-Sans", "/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]

_MONO_CANDIDATES = [
    ("CV-Mono", r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\consolab.ttf"),
    ("CV-Mono", r"C:\Windows\Fonts\cour.ttf", r"C:\Windows\Fonts\courbd.ttf"),
    ("CV-Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    ("CV-Mono", "/System/Library/Fonts/Menlo.ttc", ""),
]


def _vera_dir() -> Path:
    import reportlab
    return Path(reportlab.__file__).parent / "fonts"


def _covers_probe(font: TTFont) -> bool:
    """Whether the font really has glyphs for the probe characters."""
    try:
        table = font.face.charToGlyph
    except AttributeError:
        return False
    return all(table.get(ord(ch)) for ch in _PROBE)


def _register_pair(family: str, regular: str, bold: str) -> tuple[str, str] | None:
    """Register a regular + bold pair if the files are usable.

    Returns (regular name, bold name), or None.
    """
    if not regular or not os.path.isfile(regular):
        return None

    reg_name = family
    try:
        reg_font = TTFont(reg_name, regular)
        if not _covers_probe(reg_font):
            return None
        pdfmetrics.registerFont(reg_font)
    except Exception:  # noqa: BLE001 - damaged or unsupported font file
        return None

    bold_name = reg_name
    if bold and os.path.isfile(bold):
        try:
            pdfmetrics.registerFont(TTFont(family + "-Bold", bold))
            bold_name = family + "-Bold"
        except Exception:  # noqa: BLE001
            bold_name = reg_name

    pdfmetrics.registerFontFamily(
        family, normal=reg_name, bold=bold_name,
        italic=reg_name, boldItalic=bold_name,
    )
    return reg_name, bold_name


@lru_cache(maxsize=1)
def font_set() -> FontSet:
    """Register and return the usable font set (runs once)."""
    vera = _vera_dir()
    sans_candidates = _SANS_CANDIDATES + [
        ("CV-Sans", str(vera / "Vera.ttf"), str(vera / "VeraBd.ttf")),
    ]
    mono_candidates = _MONO_CANDIDATES + [
        # Vera has no monospaced cut, but correct accents in a text block
        # matter more than a monospaced rhythm.
        ("CV-Mono", str(vera / "Vera.ttf"), str(vera / "VeraBd.ttf")),
    ]

    sans = None
    for family, reg, bold in sans_candidates:
        sans = _register_pair(family, reg, bold)
        if sans:
            break

    mono = None
    for family, reg, bold in mono_candidates:
        mono = _register_pair(family, reg, bold)
        if mono:
            break

    if sans and mono:
        return FontSet(sans[0], sans[1], mono[0], mono[1], unicode_ok=True)
    if sans:
        return FontSet(sans[0], sans[1], sans[0], sans[1], unicode_ok=True)
    if mono:
        return FontSet(mono[0], mono[1], mono[0], mono[1], unicode_ok=True)

    # Nothing could be registered - carry on with the built-in fonts.
    return FontSet("Helvetica", "Helvetica-Bold", "Courier", "Courier-Bold",
                   unicode_ok=False)
