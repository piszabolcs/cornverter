"""
E-mails (.msg and .eml) to PDF, attachments included.

1. The header (From, To, Cc, Date, Subject) and the body become one PDF. An
   HTML body is rendered by LibreOffice when it is installed (closer to the
   original); otherwise the text is typeset with reportlab.
2. Every attachment goes through the main dispatcher (spreadsheets, images,
   Word files, archives... can all be attachments). An attached e-mail is
   converted too: an .eml completely, an embedded Outlook message from its
   own header and text body.
3. The body PDF and the attachment PDFs are merged into one document.

Attachments are saved under neutral names (`att_01.xlsx`): the original
name can be very long, contain path separators or be a reserved Windows
name - and only the extension matters to the dispatcher.
"""

from __future__ import annotations

import email
import html as html_mod
import re
import shutil
import tempfile
import time
from email import policy
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

from ..fonts import font_set
from .base import (
    ALREADY_ACCEPTED,
    EXT_CATEGORY,
    ConversionResult,
    Status,
    find_soffice,
    long_path,
    merge_pdfs,
    run_soffice_convert,
)

_KNOWN_EXTS = set(EXT_CATEGORY) | ALREADY_ACCEPTED
_FIELDS = ("From", "To", "Cc", "Date", "Subject")


def _esc(text) -> str:
    return html_mod.escape(str(text or ""))


def _msg_header(m) -> list[tuple[str, str]]:
    """Header rows of an extract_msg message."""
    values = (getattr(m, "sender", ""), getattr(m, "to", ""),
              getattr(m, "cc", ""), getattr(m, "date", ""),
              getattr(m, "subject", ""))
    return [(k, str(v or "")) for k, v in zip(_FIELDS, values)]


def _eml_header(m) -> list[tuple[str, str]]:
    return [(k, str(m.get(k, "") or "")) for k in _FIELDS]


def _html_to_text(markup: str) -> str:
    """Rough text of an HTML body, for when LibreOffice cannot render it."""
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", markup)
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", markup))


def _body_pdf_from_html(html_body: str, header: list[tuple[str, str]],
                        out_pdf: Path) -> bool:
    """Render an HTML body with LibreOffice. Returns success."""
    if not find_soffice():
        return False
    tmpdir = Path(tempfile.mkdtemp(prefix="cv_msg_html_"))
    try:
        header_rows = "".join(
            f"<tr><td style='font-weight:bold;padding:2px 8px;"
            f"vertical-align:top;white-space:nowrap'>{_esc(k)}</td>"
            f"<td style='padding:2px 8px'>{_esc(v)}</td></tr>"
            for k, v in header if v
        )
        wrapper = f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>body{{font-family:Arial,sans-serif;font-size:11pt}}
table.hdr{{border-collapse:collapse;margin-bottom:10px;
border-bottom:2px solid #444;width:100%}}</style></head>
<body><table class='hdr'>{header_rows}</table><hr/>{html_body}</body></html>"""
        html_path = tmpdir / "email.html"
        html_path.write_text(wrapper, encoding="utf-8")
        produced = run_soffice_convert(html_path, tmpdir, convert_to="pdf")
        shutil.move(str(produced), str(long_path(out_pdf)))
        return True
    except Exception:  # noqa: BLE001 - the text route takes over
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _body_pdf_from_text(text_body: str, header: list[tuple[str, str]],
                        out_pdf: Path) -> None:
    doc = SimpleDocTemplate(
        str(long_path(out_pdf)), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    fs = font_set()
    styles = getSampleStyleSheet()
    label = ParagraphStyle("lbl", parent=styles["Normal"],
                           fontName=fs.sans_bold, fontSize=9, leading=12)
    mono = ParagraphStyle("mono", parent=styles["Code"], fontName=fs.mono,
                          fontSize=8.5, leading=11)
    story = []
    for k, v in header:
        if v:
            story.append(Paragraph(f"{_esc(k)}: <font face='{fs.sans}'>"
                                   f"{_esc(v)}</font>", label))
    story.append(Spacer(1, 6 * mm))
    lines = []
    for line in (text_body or "(empty body)").splitlines():
        lines += [line[i:i + 100] for i in range(0, len(line), 100)] or [""]
    chunk = 55
    for i in range(0, len(lines) or 1, chunk):
        story.append(Preformatted("\n".join(lines[i:i + chunk]) or " ", mono))
    doc.build(story)


def _render_body(html_body: str | None, text_body: str,
                 header: list[tuple[str, str]], out_pdf: Path) -> None:
    if html_body and _body_pdf_from_html(html_body, header, out_pdf):
        return
    if not text_body.strip() and html_body:
        text_body = _html_to_text(html_body)
    _body_pdf_from_text(text_body, header, out_pdf)


def _attachment_path(workdir: Path, idx: int, filename: str) -> Path:
    """Neutral, safe file name that keeps a known extension."""
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix not in _KNOWN_EXTS:
        suffix = ".bin"
    return workdir / f"att_{idx:02d}{suffix}"


def _convert_attachment(data: bytes, name: str, idx: int,
                        workdir: Path) -> tuple[Path | None, str | None]:
    from . import convert_file  # late import (circular dependency)

    src = _attachment_path(workdir, idx, name)
    src.write_bytes(data)
    part = workdir / f"part_{idx:02d}.pdf"
    res = convert_file(src, part)
    if res.ok and part.exists():
        return part, None
    return None, f"{name}: {res.message or res.status.value}"


def _finish(path: Path, out_pdf: Path, parts: list[Path], notes: list[str],
            engine: str, start: float) -> ConversionResult:
    pages, unreadable = merge_pdfs(parts, out_pdf)
    if not pages:
        return ConversionResult(source=path, status=Status.FAILED,
                                message="The e-mail gave no readable page.",
                                engine=engine, duration_s=time.time() - start)
    message = ""
    attached = len(parts) - 1 - len(unreadable)
    left_out = notes + [f"{n}: unreadable PDF" for n in unreadable]
    if attached or left_out:
        message = f"{attached} attachment(s) converted"
        if left_out:
            message += f", {len(left_out)} left out (e.g. {left_out[0]})"
        message += "."
    return ConversionResult(source=path, status=Status.SUCCESS, output=out_pdf,
                            engine=engine, duration_s=time.time() - start,
                            message=message)


def _convert_msg(path: Path, out_pdf: Path) -> ConversionResult:
    import extract_msg

    start = time.time()
    workdir = Path(tempfile.mkdtemp(prefix="cv_msg_"))
    msg = None
    try:
        msg = extract_msg.Message(str(path))
        html_body = getattr(msg, "htmlBody", None)
        if isinstance(html_body, bytes):
            html_body = html_body.decode("utf-8", errors="replace")
        body_pdf = workdir / "part_00.pdf"
        _render_body(html_body, getattr(msg, "body", "") or "",
                     _msg_header(msg), body_pdf)

        parts, notes = [body_pdf], []
        for idx, att in enumerate(getattr(msg, "attachments", None) or [],
                                  start=1):
            name = (getattr(att, "longFilename", None)
                    or getattr(att, "shortFilename", None)
                    or f"attachment {idx}")
            data = getattr(att, "data", None)
            part, note = None, None
            try:
                if isinstance(data, (bytes, bytearray)):
                    part, note = _convert_attachment(bytes(data), name, idx,
                                                     workdir)
                elif data is not None and hasattr(data, "subject"):
                    # An Outlook message embedded in this one.
                    part = workdir / f"part_{idx:02d}.pdf"
                    _body_pdf_from_text(getattr(data, "body", "") or "",
                                        _msg_header(data), part)
                else:
                    note = f"{name}: attachment type not supported"
            except Exception as exc:  # noqa: BLE001
                part, note = None, f"{name}: {exc}"
            if part is not None:
                parts.append(part)
            if note:
                notes.append(note)
        return _finish(path, out_pdf, parts, notes, "extract_msg+merge", start)
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(source=path, status=Status.FAILED,
                                message=f"Could not convert the .msg: {exc}",
                                engine="extract_msg",
                                duration_s=time.time() - start)
    finally:
        # extract_msg keeps the .msg open: without closing it, in-place mode
        # could not move the original to the backup ("file in use").
        if msg is not None:
            try:
                msg.close()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def _convert_eml(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    workdir = Path(tempfile.mkdtemp(prefix="cv_eml_"))
    try:
        with open(long_path(path), "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        html_part = msg.get_body(preferencelist=("html",))
        text_part = msg.get_body(preferencelist=("plain",))
        body_pdf = workdir / "part_00.pdf"
        _render_body(html_part.get_content() if html_part else None,
                     text_part.get_content() if text_part else "",
                     _eml_header(msg), body_pdf)

        parts, notes = [body_pdf], []
        for idx, att in enumerate(msg.iter_attachments(), start=1):
            name = att.get_filename() or f"attachment {idx}"
            try:
                content = att.get_content()
                if att.get_content_type() == "message/rfc822":
                    data, name = content.as_bytes(), f"{name}.eml"
                elif isinstance(content, str):
                    data = content.encode("utf-8")
                else:
                    data = bytes(content)
                part, note = _convert_attachment(data, name, idx, workdir)
            except Exception as exc:  # noqa: BLE001
                part, note = None, f"{name}: {exc}"
            if part is not None:
                parts.append(part)
            if note:
                notes.append(note)
        return _finish(path, out_pdf, parts, notes, "email+merge", start)
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(source=path, status=Status.FAILED,
                                message=f"Could not convert the .eml: {exc}",
                                engine="email", duration_s=time.time() - start)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def convert(path: Path, out_pdf: Path) -> ConversionResult:
    if Path(path).suffix.lower() == ".eml":
        return _convert_eml(path, out_pdf)
    return _convert_msg(path, out_pdf)
