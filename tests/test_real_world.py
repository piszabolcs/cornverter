"""
Regression tests for real-world edge cases.

Every test here comes from a concrete problem seen on a real, mixed document
tree; they keep the fixes from slipping back.
"""

from __future__ import annotations

import gzip
import os
import zipfile
from pathlib import Path

import pytest

from conftest import (
    HUN,
    assert_no_missing_glyphs,
    assert_valid_pdf,
    make_eml,
    make_fake_xlsx_named_xls,
    make_pptx,
    make_rtf,
    make_txt,
    make_zip,
    pdf_text,
)

from cornverter.converters import Options
from cornverter.converters.base import Status, long_path
from cornverter.engine import execute_task
from cornverter.scanner import scan_in_place


# ------------------------------------------------- e-mail source file handle
def test_mail_conversion_releases_the_source_file(tmp_path: Path):
    """The mail library kept the source open, so in-place mode could not move
    the original - every e-mail failed."""
    src = tmp_path / "in"
    src.mkdir()
    make_eml(src / "mail.eml")
    backup = tmp_path / "backup"

    results = [execute_task(t, Options())
               for t in scan_in_place(src, backup, Options()).tasks]

    assert results[0].status is Status.SUCCESS, results[0].message
    assert (backup / "mail.eml").exists(), "the original could not be moved"
    assert not (src / "mail.eml").exists()


# ------------------------------------------------------------ huge scans
def test_a_very_large_image_is_not_taken_for_a_bomb(tmp_path: Path):
    """Pillow's default guard stops at ~179 MP; large drawings exceed it."""
    from PIL import Image

    from cornverter.converters import image

    big = tmp_path / "drawing.tif"
    Image.new("1", (14000, 14000), 1).save(big, compression="group4")

    result = image.convert(big, tmp_path / "drawing.pdf")

    assert result.status is Status.SUCCESS, result.message
    assert_valid_pdf(tmp_path / "drawing.pdf")


def test_ccitt_tif_is_embedded_without_reencoding(tmp_path: Path):
    from PIL import Image

    from cornverter.converters import image

    src = tmp_path / "scan.tif"
    Image.new("1", (4000, 5000), 1).save(src, compression="group4")
    out = tmp_path / "scan.pdf"

    result = image.convert(src, out)

    assert result.status is Status.SUCCESS
    assert result.engine == "img2pdf", "the direct route did not run"
    assert out.stat().st_size < src.stat().st_size * 3 + 20_000


# ------------------------------------------------ mislabelled .xls / .xlsx
def test_an_xlsx_saved_as_xls_still_converts(tmp_path: Path):
    from cornverter.converters import sheet

    src = make_fake_xlsx_named_xls(tmp_path / "parts.xls")
    out = tmp_path / "parts.pdf"
    result = sheet.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    assert result.engine == "openpyxl+reportlab"
    assert "really an xlsx" in result.message
    assert HUN in pdf_text(out)


def test_the_header_not_the_name_decides_the_format(tmp_path: Path):
    from cornverter.converters.sheet import _real_format

    assert _real_format(make_fake_xlsx_named_xls(tmp_path / "a.xls")) == "ooxml"
    ole = tmp_path / "b.xlsx"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
    assert _real_format(ole) == "ole"
    junk = tmp_path / "c.xls"
    junk.write_bytes(b"just text")
    assert _real_format(junk) == "?"


# ----------------------------------------------------------------------- RTF
def test_rtf_text_comes_through_without_libreoffice(tmp_path: Path):
    from cornverter.converters import rtftext

    src = make_rtf(tmp_path / "readme.rtf")
    out = tmp_path / "readme.pdf"
    result = rtftext.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert HUN in body and "Second paragraph" in body
    # Nothing of the font table, styles, generator or info may leak in.
    for leak in ("Times New Roman", "Arial", "Courier New", "Wingdings",
                 "heading 1", "Normal;", "Riched20", "Hidden title",
                 "Hidden author", "fnil", "rtf1"):
        assert leak not in body, f"leaked: {leak!r}"


def test_rtf_control_words_stay_out_of_the_text():
    from cornverter.converters.rtftext import rtf_to_text

    raw = (r"{\rtf1\ansi\ansicpg1250\deff0{\fonttbl{\f0\fnil Arial;}}"
           r"{\*\generator Riched20;}\pard First line\par Second line\par}")
    text = rtf_to_text(raw)

    assert "First line" in text and "Second line" in text
    assert "\\" not in text
    assert "Arial" not in text and "Riched20" not in text


def test_a_multi_entry_font_table_is_dropped_completely():
    """The first inner `}` used to end the skip, leaking later font names."""
    from cornverter.converters.rtftext import rtf_to_text

    raw = (r"{\rtf1\ansi"
           r"{\fonttbl{\f0\froman Times New Roman;}{\f1\fswiss Arial;}"
           r"{\f2\fmodern Courier New;}}"
           r"{\stylesheet{\ql Normal;}{\s1\b heading 1;}}"
           r"{\info{\title Secret title}}"
           r"\pard This is the real text.\par}")
    assert rtf_to_text(raw).strip() == "This is the real text."


def test_word_font_table_with_panose_subgroups():
    """Word writes a `{\\*\\panose ...}` subgroup into every font entry; the
    deeper `\\*` group used to end the whole `\\fonttbl` skip."""
    from cornverter.converters.rtftext import rtf_to_text

    raw = (
        r"{\rtf1\ansi\ansicpg1252\deff0"
        r"{\fonttbl"
        r"{\f0\froman\fcharset0\fprq2{\*\panose 02020603050405020304}"
        r"Times New Roman;}"
        r"{\f1\fswiss\fcharset0\fprq2{\*\panose 020b0604020202020204}Arial;}"
        r"{\f3\fnil\fcharset2{\*\panose 05000000000000000000}Symbol;}"
        r"{\f4\froman\fcharset238\fprq2 Times New Roman CE;}}"
        r"{\colortbl;\red0\green0\blue0;}"
        r"{\stylesheet{\ql\f0\fs20 Normal;}{\s1\b\fs28{\*\cs10 heading 1;}}}"
        r"{\*\generator Riched20 10.0;}"
        r"{\info{\title Secret}{\author Nobody}{\*\userprops{\propname X}}}"
        r"\pard\plain\f0\fs20 This is the only real text.\par}"
    )
    assert rtf_to_text(raw).strip() == "This is the only real text."


def test_embedded_picture_and_object_data_is_dropped():
    from cornverter.converters.rtftext import rtf_to_text

    raw = (
        r"{\rtf1\ansi\ansicpg1250"
        r"{\fonttbl{\f0\froman Times New Roman;}}"
        r"\pard\f0\fs20 First real paragraph.\par"
        r"{\pict\wmetafile8\picw100 0100090000038c0000000000480000}"
        r"Second paragraph after the picture.\par"
        r"{\object\objemb{\*\objclass Excel.Sheet}{\*\objdata 0105000002}}"
        r"Third paragraph after the object.\par}"
    )
    lines = [ln for ln in rtf_to_text(raw).split("\n") if ln.strip()]
    assert lines == ["First real paragraph.",
                     "Second paragraph after the picture.",
                     "Third paragraph after the object."]


def test_a_non_rtf_file_fails(tmp_path: Path):
    from cornverter.converters import rtftext

    src = tmp_path / "fake.rtf"
    src.write_text("plain text", encoding="utf-8")
    assert rtftext.convert(src, tmp_path / "x.pdf").status is Status.FAILED


# ---------------------------------------------------------------------- PPTX
def test_pptx_slide_text_comes_through(tmp_path: Path):
    from cornverter.converters import pptxml

    src = make_pptx(tmp_path / "deck.pptx", slides=3, note="Speaker note")
    out = tmp_path / "deck.pdf"
    result = pptxml.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert "Slide 1 title" in body and "Slide 3 title" in body
    assert HUN in body and "Speaker note" in body
    assert "3 slide(s) (3 with text)" in result.message


def test_an_image_only_pptx_is_skipped_clearly(tmp_path: Path):
    from cornverter.converters import pptxml

    src = make_pptx(tmp_path / "images.pptx", slides=2, empty=True)
    result = pptxml.convert(src, tmp_path / "images.pdf")
    assert result.status is Status.SKIPPED
    assert "LibreOffice" in result.message


def test_a_zip_that_is_not_a_pptx_fails(tmp_path: Path):
    from cornverter.converters import pptxml

    src = tmp_path / "fake.pptx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("something.txt", b"x")
    assert pptxml.convert(src, tmp_path / "x.pdf").status is Status.FAILED


# ------------------------------------------------------- archives / bsdtar
def test_a_plain_gzip_file_is_unpacked(tmp_path: Path):
    """tarfile fails on a non-tar .gz; it is then read as plain gzip."""
    from cornverter.converters import archive

    src = tmp_path / "notes.txt.gz"
    with gzip.open(src, "wb") as f:
        f.write(f"{HUN}\ngzipped content\n".encode("utf-8"))

    result = archive.convert(src, tmp_path / "notes.pdf")

    assert result.status is Status.SUCCESS, result.message
    assert "gzipped content" in pdf_text(tmp_path / "notes.pdf")


def test_bsdtar_discovery_finds_the_windows_tar_exe():
    from cornverter.converters.archive import find_bsdtar

    if os.name != "nt":
        pytest.skip("Windows-specific discovery.")
    exe = find_bsdtar()
    if exe is None:
        pytest.skip("No bsdtar on this computer.")
    assert os.path.isfile(exe)


def test_an_archive_without_convertible_content_is_skipped(tmp_path: Path):
    """A package of CAD files: "nothing to convert" is the right answer."""
    from cornverter.converters import archive

    src = make_zip(tmp_path / "cad.zip", {"part.stp": b"ISO-10303-21;\n"})
    result = archive.convert(src, tmp_path / "cad.pdf")

    assert result.status is Status.SKIPPED
    assert "Nothing convertible" in result.message


# ------------------------------------------------ mixed real folder, in place
def test_a_typical_mixed_folder_in_place(tmp_path: Path):
    src = tmp_path / "Docs" / "Machine-01 (1995)"
    (src / "error-codes" / "TIF").mkdir(parents=True)
    make_txt(src / "protocol.txt")
    make_rtf(src / "readme.rtf")
    make_pptx(src / "slides.pptx", slides=2)
    make_fake_xlsx_named_xls(src / "parts.xls")
    make_eml(src / "error-codes" / "mail.eml", html=True)
    (src / "error-codes" / "TIF" / "ready.pdf").write_bytes(b"%PDF-1.4\n")

    root = tmp_path / "Docs"
    backup = tmp_path / "Docs_originals"
    results = [execute_task(t, Options())
               for t in scan_in_place(root, backup, Options()).tasks]

    failed = [(r.source.name, r.message) for r in results
              if r.status is Status.FAILED]
    assert not failed, failed
    assert len(results) == 5      # the PDF is left alone

    for rel in ("protocol_from_txt.pdf", "readme_from_rtf.pdf",
                "slides_from_pptx.pdf", "parts_from_xls.pdf",
                "error-codes/mail_from_eml.pdf"):
        assert_valid_pdf(src / rel)
    moved = backup / "Machine-01 (1995)"
    assert (moved / "protocol.txt").exists()
    assert (moved / "error-codes" / "mail.eml").exists()
    assert (src / "error-codes" / "TIF" / "ready.pdf").exists()
    assert not os.path.exists(
        long_path(moved / "error-codes" / "TIF" / "ready.pdf"))
