"""Scanner (task list) and report writer tests."""

from __future__ import annotations

import csv
from pathlib import Path

from conftest import make_csv, make_png, make_txt, make_xlsx, make_zip

from cornverter.converters import Options
from cornverter.converters.base import ConversionResult, Status
from cornverter.engine import RunOutcome, write_reports
from cornverter.report import write_csv, write_markdown
from cornverter.scanner import Task, scan


def _tree(root: Path) -> Path:
    """Mixed input folder with a sub-folder."""
    (root / "sub").mkdir(parents=True, exist_ok=True)
    make_txt(root / "notes.txt")
    make_csv(root / "sub" / "data.csv")
    make_png(root / "picture.png")
    make_xlsx(root / "table.xlsx", sheets=1, with_empty=False)
    make_zip(root / "bundle.zip", {"inside.txt": b"x"})
    (root / "junk.tmp").write_bytes(b"x")
    (root / "unknown.xyz").write_bytes(b"x")
    (root / "ready.pdf").write_bytes(b"%PDF-1.4\n")
    return root


def test_scan_categorizes_and_counts(tmp_path: Path):
    summary = scan(_tree(tmp_path / "in"), tmp_path / "out", Options())

    assert summary.total_files == 8
    assert summary.skipped_junk == 1
    assert summary.unknown == 1
    assert summary.skipped_accepted == 0   # the .pdf is copied by default
    assert len(summary.tasks) == 6
    assert summary.total_bytes_to_convert > 0
    assert summary.human_total().endswith(("B", "KB", "MB"))


def test_output_mirrors_the_folder_tree(tmp_path: Path):
    src = _tree(tmp_path / "in")
    out = tmp_path / "out"
    by_name = {t.source.name: t.output for t in scan(src, out, Options()).tasks}

    assert by_name["data.csv"] == out / "sub" / "data.pdf"
    assert by_name["notes.txt"] == out / "notes.pdf"


def test_same_stem_files_get_deterministic_names(tmp_path: Path):
    """No file wins the plain name by walk order: every one of a same-stem
    group shows its extension, a unique stem keeps the plain name."""
    src = tmp_path / "in"
    src.mkdir()
    make_csv(src / "data.csv")
    make_csv(src / "data.tsv", delimiter="\t")
    make_zip(src / "data.zip", {"a.txt": b"x"})
    (src / "data.7z").write_bytes(b"7z")
    make_txt(src / "solo.txt")

    names = sorted(t.output.name
                   for t in scan(src, tmp_path / "out", Options()).tasks)

    assert names == ["data_7z.pdf", "data_csv.pdf", "data_tsv.pdf",
                     "data_zip.pdf", "solo.pdf"]


def test_output_inside_the_input_is_not_scanned_again(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "original.txt")
    out = src / "PDF"
    out.mkdir()
    (out / "earlier.pdf").write_bytes(b"%PDF-1.4\n")

    summary = scan(src, out, Options(convert_accepted=True))
    assert [t.source.name for t in summary.tasks] == ["original.txt"]


def test_options_filter_the_task_list(tmp_path: Path):
    src = _tree(tmp_path / "in")

    only_text = scan(src, tmp_path / "o1", Options(
        convert_excel=False, convert_images=False, expand_archives=False,
        convert_accepted=False))
    assert {t.category for t in only_text.tasks} == {"text"}
    assert only_text.skipped_by_option == 3
    assert only_text.skipped_accepted == 1


# ------------------------------------------------------------------ reports
def _results() -> list[ConversionResult]:
    return [
        ConversionResult(source=Path("C:/in/a.txt"), status=Status.SUCCESS,
                         output=Path("C:/out/a.pdf"), engine="reportlab-text",
                         duration_s=0.5),
        ConversionResult(source=Path("C:/in/sub/c.rtf"), status=Status.FAILED,
                         engine="libreoffice", duration_s=0.1,
                         message="LibreOffice needed | here\nsecond line"),
        ConversionResult(source=Path("C:/in/d.zip"), status=Status.SKIPPED,
                         engine="archive",
                         message="Password-protected archive - skipped."),
        ConversionResult(source=Path("C:/in/e.xyz"), status=Status.UNSUPPORTED,
                         engine="dispatch"),
    ]


def test_csv_log_has_one_row_per_file_with_relative_paths(tmp_path: Path):
    out = tmp_path / "logs" / "log.csv"
    write_csv(_results(), out, root=Path("C:/in"))

    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["source_file", "status", "engine", "output",
                       "duration_s", "message"]
    assert len(rows) == 5
    assert rows[2][:2] == ["sub/c.rtf", "failed"]


def test_markdown_report_keeps_tables_intact_and_lists_skipped(tmp_path: Path):
    out = tmp_path / "report.md"
    write_markdown(_results(), out, input_dir="C:/in", output_dir="C:/out",
                   root=Path("C:/in"))
    body = out.read_text(encoding="utf-8")

    assert "# CornVerter conversion report" in body
    assert "- Converted: 1" in body and "- Failed: 1" in body
    assert "- Skipped: 1" in body and "- Unsupported: 1" in body
    # A multi-line message with a pipe stays on one escaped table row.
    assert "| `sub/c.rtf` | libreoffice | LibreOffice needed \\| here " \
           "second line |" in body
    # Skipped items are listed with their reason.
    assert "Password-protected archive" in body and "`e.xyz`" in body
    assert "| reportlab-text | 1 |" in body


def test_cancelled_run_is_reported(tmp_path: Path):
    leftover = Task(source=tmp_path / "in" / "late.txt",
                    output=tmp_path / "out" / "late.pdf", category="text",
                    size=1)
    outcome = RunOutcome(results=_results()[:1], cancelled=[leftover])

    md = write_reports(outcome, tmp_path / "out", tmp_path / "in",
                       tmp_path / "out")

    body = md.read_text(encoding="utf-8")
    assert md.name.startswith("cornverter_report_")
    assert "The run was cancelled: 1 file(s) were not processed." in body
    assert "- Cancelled: 1" in body
    assert (md.with_suffix(".csv")).exists()
