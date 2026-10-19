"""E-mail attachments, text encodings and the LibreOffice route."""

from __future__ import annotations

import io
import subprocess
import tempfile
import threading
import time
import types
from email.message import EmailMessage
from pathlib import Path

import pytest

from conftest import HUN, make_txt, make_xlsx, pdf_pages, pdf_text

from cornverter.converters import base, msg, office, text
from cornverter.converters.base import SofficeError, Status


# ------------------------------------------------------------------- e-mail
def test_eml_attachments_are_converted_and_merged(tmp_path: Path):
    from PIL import Image

    m = EmailMessage()
    m["From"] = "sender@example.com"
    m["To"] = "team@example.com"
    m["Subject"] = "Quarterly figures"
    m.set_content("Body text of the mail.")
    m.add_attachment(b"attachment text inside\n", maintype="text",
                     subtype="plain", filename="notes.txt")
    png = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(png, "PNG")
    m.add_attachment(png.getvalue(), maintype="image", subtype="png",
                     filename="../../CON.png")
    src = tmp_path / "mail.eml"
    src.write_bytes(m.as_bytes())
    out = tmp_path / "mail.pdf"

    result = msg.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    assert pdf_pages(out) == 3
    body = pdf_text(out)
    assert "Body text of the mail" in body
    assert "attachment text inside" in body
    assert "2 attachment(s) converted" in result.message


def test_msg_attachments_and_an_embedded_mail(tmp_path: Path, monkeypatch):
    import extract_msg

    inner = types.SimpleNamespace(sender="inner@example.com", to="", cc="",
                                  date="", subject="Forwarded note",
                                  body="inner body")
    stub = types.SimpleNamespace(
        sender="sender@example.com", to="team@example.com", cc=None,
        date="2026-10-12", subject="Stub mail", body="outer body",
        htmlBody=None, close=lambda: None,
        attachments=[
            types.SimpleNamespace(longFilename="..\\..\\" + "x" * 300 + ".txt",
                                  data=b"attached text\n"),
            types.SimpleNamespace(longFilename="NUL.txt", data=b"second\n"),
            types.SimpleNamespace(longFilename="fwd.msg", data=inner),
        ])
    monkeypatch.setattr(extract_msg, "Message", lambda path: stub)
    src = tmp_path / "mail.msg"
    src.write_bytes(b"stub")
    out = tmp_path / "mail.pdf"

    result = msg.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    body = pdf_text(out)
    for expected in ("outer body", "attached text", "second",
                     "Forwarded note", "inner body"):
        assert expected in body
    assert "3 attachment(s) converted" in result.message


# --------------------------------------------------------------------- text
def test_utf16_text_file_is_decoded(tmp_path: Path):
    src = tmp_path / "unicode.txt"
    src.write_bytes(HUN.encode("utf-16"))
    out = tmp_path / "unicode.pdf"

    assert text.convert(src, out).status is Status.SUCCESS
    assert HUN in pdf_text(out)


# ------------------------------------------------------------- LibreOffice
def test_libreoffice_failure_reason_is_kept_when_the_fallback_runs(
        tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, "_SOFFICE_CACHE", "C:/fake/soffice.exe")

    def boom(*a, **k):
        raise SofficeError("profile trouble")

    monkeypatch.setattr(office, "run_soffice_convert", boom)
    src = make_xlsx(tmp_path / "costs.xlsx", sheets=1, with_empty=False)

    result = office.convert(src, tmp_path / "costs.pdf")

    assert result.status is Status.SUCCESS
    assert result.engine == "openpyxl+reportlab"
    assert result.message.startswith("LibreOffice failed: profile trouble")


def test_a_too_long_profile_path_is_reported(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(base, "_SOFFICE_CACHE", "C:/fake/soffice.exe")
    monkeypatch.setenv("CORNVERTER_LO_PROFILE", "C:/" + "p" * 200)

    with pytest.raises(SofficeError, match="too long"):
        base.run_soffice_convert(make_txt(tmp_path / "a.txt"), tmp_path)


@pytest.mark.libreoffice
def test_libreoffice_keeps_every_cell_readable_with_a_long_temp(
        tmp_path: Path, monkeypatch):
    long_temp = tmp_path / ("t" * 60) / ("u" * 60)
    long_temp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(long_temp))
    src = make_xlsx(tmp_path / "costs.xlsx", sheets=1, with_empty=False)
    out = tmp_path / "costs.pdf"

    result = office.convert(src, out)

    assert result.status is Status.SUCCESS, result.message
    assert result.engine == "libreoffice", result.message
    body = pdf_text(out)
    assert "###" not in body
    assert HUN in body
    assert "2026" in body


@pytest.mark.libreoffice
def test_cancel_kills_a_running_libreoffice_call(tmp_path: Path,
                                                 monkeypatch):
    started: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording(*a, **k):
        proc = real_popen(*a, **k)
        started.append(proc)
        return proc

    monkeypatch.setattr(base.subprocess, "Popen", recording)
    src = make_txt(tmp_path / "doc.txt")
    errors: list[str] = []

    def convert():
        try:
            base.run_soffice_convert(src, tmp_path / "out")
        except SofficeError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=convert)
    worker.start()
    try:
        deadline = time.monotonic() + 30
        while not started and time.monotonic() < deadline:
            time.sleep(0.05)
        base.request_cancel()
        worker.join(timeout=20)
    finally:
        base.reset_cancel()

    assert not worker.is_alive()
    assert errors == ["Cancelled."]
    assert started[0].poll() is not None
