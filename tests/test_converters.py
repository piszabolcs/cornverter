"""Converter tests: does the input really become a readable PDF?"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import (
    HUN,
    assert_no_missing_glyphs,
    assert_valid_pdf,
    make_csv,
    make_docx,
    make_eml,
    make_multipage_tif,
    make_png,
    make_txt,
    make_xlsx,
    make_zip,
    pdf_pages,
    pdf_text,
)

from cornverter.converters import Options, convert_file
from cornverter.converters.base import Status, categorize, human_size


# --------------------------------------------------------------------- text
def test_txt_becomes_pdf_with_correct_accents(workdir: Path):
    from cornverter.converters import text

    src = make_txt(workdir / "sample.txt", f"{HUN}\nsecond line\n")
    out = workdir / "sample.pdf"
    result = text.convert(src, out)

    assert result.status is Status.SUCCESS
    assert_valid_pdf(out)
    assert_no_missing_glyphs(out)
    assert HUN in pdf_text(out)


def test_empty_txt_does_not_break(workdir: Path):
    from cornverter.converters import text

    src = make_txt(workdir / "empty.txt", "")
    out = workdir / "empty.pdf"
    assert text.convert(src, out).status is Status.SUCCESS
    assert_valid_pdf(out)


def test_long_lines_wrap_onto_several_pages(workdir: Path):
    from cornverter.converters import text

    src = make_txt(workdir / "long.txt", ("x" * 5000 + "\n") * 40)
    out = workdir / "long.pdf"
    assert text.convert(src, out).status is Status.SUCCESS
    assert pdf_pages(out) > 1


def test_cp1250_file_is_readable(workdir: Path):
    from cornverter.converters import text

    src = workdir / "cp1250.txt"
    src.write_bytes("Ékezetes cp1250 szöveg".encode("cp1250"))
    out = workdir / "cp1250.pdf"
    assert text.convert(src, out).status is Status.SUCCESS
    assert "Ékezetes" in pdf_text(out)


def test_csv_is_rendered_as_a_table(workdir: Path):
    from cornverter.converters import text

    src = make_csv(workdir / "data.csv")
    out = workdir / "data.pdf"
    result = text.convert(src, out)

    assert result.status is Status.SUCCESS
    assert result.engine == "reportlab-table"
    assert_valid_pdf(out)
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert "Note" in body and "fine" in body


def test_tsv_splits_on_tabs(workdir: Path):
    from cornverter.converters import text

    src = make_csv(workdir / "data.tsv", delimiter="\t")
    out = workdir / "data_tsv.pdf"
    assert text.convert(src, out).engine == "reportlab-table"
    assert "Value" in pdf_text(out)


# -------------------------------------------------------------- spreadsheet
def test_every_xlsx_sheet_comes_through(workdir: Path):
    from cornverter.converters import sheet

    src = make_xlsx(workdir / "table.xlsx", sheets=3)
    out = workdir / "table.pdf"
    result = sheet.convert(src, out)

    assert result.status is Status.SUCCESS
    assert_valid_pdf(out)
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert HUN in body
    assert "Sheet 2" in body and "Sheet 3" in body
    # The empty sheet is left out, the three with content get a page each.
    assert pdf_pages(out) == 3


def test_xlsx_dates_numbers_and_flags_are_formatted(workdir: Path):
    from cornverter.converters import sheet

    src = make_xlsx(workdir / "formats.xlsx", sheets=1, with_empty=False)
    out = workdir / "formats.pdf"
    assert sheet.convert(src, out).status is Status.SUCCESS
    body = pdf_text(out)
    assert "2026-08-13" in body                 # date without time
    assert "2026-08-13 09:30:00" in body        # date with time
    assert "TRUE" in body and "FALSE" in body   # booleans
    assert "2.5" in body


def test_empty_spreadsheet_is_skipped(workdir: Path):
    import openpyxl

    from cornverter.converters import sheet

    src = workdir / "nothing.xlsx"
    openpyxl.Workbook().save(src)
    assert sheet.convert(src, workdir / "nothing.pdf").status is Status.SKIPPED


def test_damaged_xlsx_fails_without_stopping_anything(workdir: Path):
    from cornverter.converters import sheet

    src = workdir / "broken.xlsx"
    src.write_bytes(b"this is not an xlsx")
    result = sheet.convert(src, workdir / "broken.pdf")
    assert result.status is Status.FAILED
    assert "failed" in result.message.lower()


# --------------------------------------------------------------------- Word
def test_docx_paragraphs_and_tables_come_through(workdir: Path):
    from cornverter.converters import wordml

    src = make_docx(workdir / "doc.docx")
    out = workdir / "doc.pdf"
    result = wordml.convert(src, out)

    assert result.status is Status.SUCCESS
    assert_valid_pdf(out)
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert "Heading" in body and HUN in body
    assert "Header A" in body and "value 2" in body


def test_a_non_word_file_fails(workdir: Path):
    from cornverter.converters import wordml

    src = workdir / "not_word.docx"
    src.write_bytes(b"just junk")
    assert wordml.convert(src, workdir / "x.pdf").status is Status.FAILED


# -------------------------------------------------------------------- images
def test_png_goes_into_a_pdf(workdir: Path):
    from cornverter.converters import image

    src = make_png(workdir / "picture.png")
    out = workdir / "picture.pdf"
    result = image.convert(src, out)

    assert result.status is Status.SUCCESS
    assert result.engine == "img2pdf"
    assert_valid_pdf(out)
    assert pdf_pages(out) == 1


def test_every_page_of_a_multipage_tif_comes_through(workdir: Path):
    from cornverter.converters import image

    src = make_multipage_tif(workdir / "scan.tif", pages=3)
    out = workdir / "scan.pdf"
    result = image.convert(src, out)

    assert result.status is Status.SUCCESS
    assert pdf_pages(out) == 3
    assert "3-page" in result.message


def test_cmyk_and_alpha_images_work_too(workdir: Path):
    from PIL import Image

    from cornverter.converters import image

    cmyk = workdir / "cmyk.jpg"
    Image.new("CMYK", (300, 200)).save(cmyk)
    rgba = workdir / "alpha.png"
    Image.new("RGBA", (300, 200), (255, 0, 0, 120)).save(rgba)

    for src in (cmyk, rgba):
        out = src.with_suffix(".pdf")
        assert image.convert(src, out).status is Status.SUCCESS
        assert_valid_pdf(out)


def test_a_non_image_fails(workdir: Path):
    from cornverter.converters import image

    src = workdir / "fake.png"
    src.write_bytes(b"not an image")
    assert image.convert(src, workdir / "fake.pdf").status is Status.FAILED


def test_there_is_no_ocr_in_the_program():
    """The image converter has nothing to do with OCR (owner's decision)."""
    from cornverter.converters import base, image

    source = Path(image.__file__).read_text(encoding="utf-8").lower()
    for banned in ("ocrmypdf", "tesseract", "pytesseract", "do_ocr"):
        assert banned not in source, f"OCR leftover: {banned}"
    assert not hasattr(base, "find_tesseract")
    assert not hasattr(Options(), "ocr_enabled")


# -------------------------------------------------------------------- e-mail
def test_eml_with_a_plain_text_body(workdir: Path):
    from cornverter.converters import msg

    src = make_eml(workdir / "mail.eml")
    out = workdir / "mail.pdf"
    result = msg.convert(src, out)

    assert result.status is Status.SUCCESS
    assert_valid_pdf(out)
    assert_no_missing_glyphs(out)
    body = pdf_text(out)
    assert "sender@example.com" in body
    assert "Test subject" in body
    assert HUN in body


def test_eml_html_body_keeps_its_text_without_libreoffice(workdir: Path):
    from cornverter.converters import msg

    src = make_eml(workdir / "html.eml", html=True)
    out = workdir / "html.pdf"
    assert msg.convert(src, out).status is Status.SUCCESS
    assert HUN in pdf_text(out)


# ------------------------------------------------------------------ archives
def test_zip_content_is_merged_into_one_pdf(workdir: Path):
    from cornverter.converters import archive

    src = make_zip(workdir / "bundle.zip", {
        "first.txt": f"{HUN}\n".encode("utf-8"),
        "sub/second.txt": "second file\n".encode("utf-8"),
    })
    out = workdir / "bundle.pdf"
    result = archive.convert(src, out)

    assert result.status is Status.SUCCESS
    assert_valid_pdf(out)
    body = pdf_text(out)
    assert HUN in body and "second file" in body
    assert "2 file(s) merged" in result.message


def test_zip_without_convertible_content_is_skipped(workdir: Path):
    from cornverter.converters import archive

    src = make_zip(workdir / "junk.zip", {"a.tmp": b"x", "b.ini": b"y"})
    assert archive.convert(src, workdir / "junk.pdf").status is Status.SKIPPED


def test_damaged_zip_is_skipped_with_a_message(workdir: Path):
    from cornverter.converters import archive

    src = workdir / "broken.zip"
    src.write_bytes(b"PK not real")
    result = archive.convert(src, workdir / "broken.pdf")
    assert result.status is Status.SKIPPED
    assert result.message


# ---------------------------------------------------------------- dispatcher
@pytest.mark.parametrize("name,expected", [
    ("a.txt", "text"), ("a.csv", "text"),
    ("a.xlsx", "office"), ("a.docm", "office"), ("a.rtf", "office"),
    ("a.msg", "msg"), ("a.eml", "msg"),
    ("a.tif", "image"), ("a.zip", "archive"), ("a.7z", "archive"),
    ("a.pdf", "accepted"), ("a.docx", "accepted"),
    ("a.tmp", "junk"), ("a.xyz", "unknown"), ("no_extension", "unknown"),
])
def test_categorize(name, expected):
    assert categorize(Path(name)) == expected


def test_dispatcher_picks_the_right_engine(workdir: Path):
    cases = {
        make_txt(workdir / "d.txt"): "reportlab-text",
        make_csv(workdir / "d.csv"): "reportlab-table",
        make_png(workdir / "d.png"): "img2pdf",
        make_xlsx(workdir / "d.xlsx", sheets=1, with_empty=False):
            "openpyxl+reportlab",
        make_docx(workdir / "d.docx"): "wordml+reportlab",
    }
    for src, engine in cases.items():
        out = workdir / "out" / (src.stem + "_out.pdf")
        result = convert_file(src, out, Options())
        assert result.status is Status.SUCCESS, f"{src.name}: {result.message}"
        assert result.engine == engine, f"{src.name} -> {result.engine}"
        assert_valid_pdf(out)


def test_an_existing_pdf_is_copied(workdir: Path):
    from cornverter.converters import text

    src = make_txt(workdir / "base.txt")
    original = workdir / "base.pdf"
    text.convert(src, original)

    out = workdir / "copy" / "base.pdf"
    result = convert_file(original, out, Options())
    assert result.status is Status.SUCCESS
    assert result.engine == "copy"
    assert out.read_bytes() == original.read_bytes()


def test_junk_is_skipped_and_unknown_is_unsupported(workdir: Path):
    junk = workdir / "something.tmp"
    junk.write_bytes(b"x")
    assert convert_file(junk, workdir / "x.pdf").status is Status.SKIPPED
    unknown = workdir / "something.xyz"
    unknown.write_bytes(b"x")
    assert convert_file(unknown, workdir / "y.pdf").status is Status.UNSUPPORTED


def test_switched_off_options_skip(workdir: Path):
    opts = Options(convert_msg=False, expand_archives=False)
    mail = make_eml(workdir / "mail.eml")
    assert convert_file(mail, workdir / "x.pdf", opts).status is Status.SKIPPED
    bundle = make_zip(workdir / "z.zip", {"a.txt": b"x"})
    assert convert_file(bundle, workdir / "z.pdf", opts).status is Status.SKIPPED


@pytest.mark.parametrize("name", ["doc.odt", "table.ods", "old.doc",
                                  "table.xlsb"])
def test_formats_without_fallback_say_libreoffice_is_needed(workdir: Path,
                                                            name: str):
    from cornverter.converters import office

    src = workdir / name
    src.write_bytes(b"\xd0\xcf\x11\xe0 anything")
    result = office.convert(src, workdir / "out.pdf")
    assert result.status is Status.FAILED
    assert "LibreOffice" in result.message


@pytest.mark.parametrize("name,engine", [
    ("doc.rtf", "rtftext"), ("deck.pptx", "pptxml"), ("table.xlsx", "openpyxl"),
])
def test_these_formats_have_a_builtin_fallback(workdir: Path, name: str,
                                               engine: str):
    from conftest import make_pptx, make_rtf

    from cornverter.converters import office

    src = workdir / name
    if name.endswith(".rtf"):
        make_rtf(src)
    elif name.endswith(".pptx"):
        make_pptx(src, slides=1)
    else:
        make_xlsx(src, sheets=1, with_empty=False)

    result = office.convert(src, workdir / "out.pdf")
    assert result.status is Status.SUCCESS, result.message
    assert engine in result.engine


@pytest.mark.parametrize("size,unit", [(0, "B"), (2048, "KB"),
                                       (5 * 1024 ** 2, "MB"),
                                       (3 * 1024 ** 3, "GB")])
def test_human_size_units(size, unit):
    assert human_size(size).endswith(unit)
