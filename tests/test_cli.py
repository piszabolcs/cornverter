"""Command line: the same engine, no Qt, honest exit codes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import make_csv, make_txt, pdf_text

from cornverter.cli import main


def test_a_single_file_becomes_a_pdf_next_to_it_without_overwriting(
        tmp_path: Path):
    src = make_txt(tmp_path / "report.txt", "fresh content\n")
    existing = tmp_path / "report.pdf"
    existing.write_bytes(b"%PDF-1.4 unrelated")

    assert main([str(src)]) == 0

    assert existing.read_bytes() == b"%PDF-1.4 unrelated"
    assert "fresh content" in pdf_text(tmp_path / "report_from_txt.pdf")


def test_a_folder_goes_into_an_output_folder_with_a_report(tmp_path: Path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    make_txt(src / "a.txt")
    make_csv(src / "sub" / "b.csv")
    out = tmp_path / "pdfs"

    assert main([str(src), "--out", str(out)]) == 0

    assert (out / "a.pdf").exists() and (out / "sub" / "b.pdf").exists()
    assert len(list(out.glob("cornverter_report_*.md"))) == 1


def test_invalid_arguments_exit_with_2(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    file = make_txt(src / "a.txt")

    for argv in ([str(src), "--out", str(src)],      # output = input
                 [str(file), "--inplace"],            # in place needs a folder
                 [str(tmp_path / "missing")]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 2


def test_the_command_line_does_not_load_qt(tmp_path: Path):
    import subprocess

    code = ("import sys; from cornverter.cli import main; "
            "main([sys.argv[1]]); "
            "print('PySide6' in sys.modules)")
    src = make_txt(tmp_path / "x.txt")
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", code, str(src)], cwd=root,
                         capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().endswith("False"), out.stdout + out.stderr
