"""
Spreadsheets to PDF without LibreOffice.

Handled: .xlsx, .xlsm (openpyxl) and .xls (xlrd)

The fallback of office.py: spreadsheets still become searchable PDFs on a
computer without LibreOffice. The formatting is lost, the CONTENT - every
sheet, every cell - is kept as text.

Every sheet starts on a new page; its first row is shown as the header.
"""

from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path

from .base import ConversionResult, Status, long_path
from .tablepdf import Section, render

# Safety limit: one runaway sheet must not produce a PDF of thousands of pages.
MAX_ROWS_PER_SHEET = 5000

# Mislabelled extensions are common (an .xlsx saved as .xls), so the first
# bytes of the file decide, not the name.
_ZIP_MAGIC = b"PK\x03\x04"        # xlsx / xlsm (Office Open XML = ZIP)
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # xls (legacy OLE2 / BIFF)


def _real_format(path: Path) -> str:
    """The real format from the file header: "ooxml", "ole" or "?"."""
    try:
        with open(long_path(path), "rb") as f:
            head = f.read(8)
    except OSError:
        return "?"
    if head.startswith(_ZIP_MAGIC):
        return "ooxml"
    if head.startswith(_OLE_MAGIC):
        return "ole"
    return "?"


def _fmt(value) -> str:
    """A cell value as readable text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, _dt.datetime):
        # No fake 00:00:00 when there is no time part.
        if (value.hour, value.minute, value.second) == (0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, _dt.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float):
        # 3.0 prints as 3, other decimals are kept.
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _trim(rows: list[list[str]]) -> list[list[str]]:
    """Drop fully empty rows at the end and empty columns on the right."""
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        return []
    last_col = 0
    for row in rows:
        for i, cell in enumerate(row):
            if cell.strip():
                last_col = max(last_col, i + 1)
    if last_col == 0:
        return []
    return [row[:last_col] for row in rows]


def _limit_note(truncated: bool) -> str:
    return (f"Only the first {MAX_ROWS_PER_SHEET} rows of this sheet are "
            f"shown." if truncated else "")


def _sections_xlsx(path: Path) -> list[Section]:
    import openpyxl

    # A file object, not a path: given a path, openpyxl checks the EXTENSION
    # and rejects an xlsx saved as .xls with a misleading "old .xls format
    # not supported" error. Read from a stream, the content decides.
    with open(long_path(path), "rb") as fh:
        # data_only=True: the values Excel calculated, not the formulas.
        wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
        try:
            sections: list[Section] = []
            for ws in wb.worksheets:
                if ws.sheet_state != "visible":
                    continue
                rows: list[list[str]] = []
                truncated = False
                for r_i, row in enumerate(ws.iter_rows(values_only=True)):
                    if r_i >= MAX_ROWS_PER_SHEET:
                        truncated = True
                        break
                    rows.append([_fmt(c) for c in row])
                rows = _trim(rows)
                if rows:
                    sections.append(Section(heading=f"Sheet: {ws.title}",
                                            rows=rows,
                                            note=_limit_note(truncated)))
            return sections
        finally:
            wb.close()


def _sections_xls(path: Path) -> list[Section]:
    import xlrd

    book = xlrd.open_workbook(str(long_path(path)))
    sections: list[Section] = []
    for sh in book.sheets():
        truncated = sh.nrows > MAX_ROWS_PER_SHEET
        rows = _trim([[_fmt(v) for v in sh.row_values(r)]
                      for r in range(min(sh.nrows, MAX_ROWS_PER_SHEET))])
        if rows:
            sections.append(Section(heading=f"Sheet: {sh.name}", rows=rows,
                                    note=_limit_note(truncated)))
    return sections


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    ext = path.suffix.lower()
    if ext not in (".xlsx", ".xlsm", ".xls"):
        return ConversionResult(
            source=path, status=Status.UNSUPPORTED,
            message=f"The spreadsheet renderer does not handle {ext}",
            engine="sheet", duration_s=time.time() - start,
        )

    # The file header, not the extension, picks the reader.
    fmt = _real_format(path)
    if fmt == "?":
        fmt = "ole" if ext == ".xls" else "ooxml"
    mislabeled = (fmt == "ooxml" and ext == ".xls") or \
                 (fmt == "ole" and ext in (".xlsx", ".xlsm"))

    try:
        if fmt == "ooxml":
            sections = _sections_xlsx(path)
            engine = "openpyxl+reportlab"
        else:
            sections = _sections_xls(path)
            engine = "xlrd+reportlab"

        if not sections:
            return ConversionResult(
                source=path, status=Status.SKIPPED,
                message="Every sheet of the spreadsheet is empty.",
                engine=engine, duration_s=time.time() - start,
            )

        Path(long_path(out_pdf)).parent.mkdir(parents=True, exist_ok=True)
        render(long_path(out_pdf), path.name, sections)
        note = (f"{len(sections)} sheet(s), without LibreOffice "
                f"(content without formatting).")
        if mislabeled:
            real = "xlsx" if fmt == "ooxml" else "xls"
            note += f" The file is named {ext} but is really an {real}."
        return ConversionResult(
            source=path, status=Status.SUCCESS, output=out_pdf,
            engine=engine, duration_s=time.time() - start, message=note,
        )
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(
            source=path, status=Status.FAILED,
            message=f"Spreadsheet to PDF failed: {exc}",
            engine="sheet", duration_s=time.time() - start,
        )
