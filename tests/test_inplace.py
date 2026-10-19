"""
In-place conversion: the PDF goes next to the original, the original into
the backup folder.

These tests look at the file system on purpose - the point of the feature is
WHAT ends up WHERE, and what is left behind.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import (
    HUN,
    assert_valid_pdf,
    make_csv,
    make_docx,
    make_multipage_tif,
    make_txt,
    make_xlsx,
    pdf_text,
)

from cornverter.converters import Options
from cornverter.converters.base import Status, long_path, plain_path, walk_files
from cornverter.engine import TMP_SUFFIX, execute_task, move_original
from cornverter.scanner import converted_name, default_backup_dir, scan_in_place


def _run(tasks, opts=None):
    return [execute_task(t, opts or Options()) for t in tasks]


def _leftovers(root: Path) -> list[Path]:
    return [p for p in walk_files(root) if p.name.endswith(TMP_SUFFIX)]


# ------------------------------------------------------------------- naming
@pytest.mark.parametrize("name,expected", [
    ("report.tif", "report_from_tif.pdf"),
    ("report.xls", "report_from_xls.pdf"),
    ("SAFETY 1. '95D.tif", "SAFETY 1. '95D_from_tif.pdf"),
    ("two.dot.name.msg", "two.dot.name_from_msg.pdf"),
    ("SMALL.BIG.TIF", "SMALL.BIG_from_tif.pdf"),
])
def test_converted_name_tells_the_source_type(name, expected):
    assert converted_name(Path(name)) == expected


def test_default_backup_folder_sits_next_to_the_input():
    src = Path(r"C:\data\Documents")
    backup = default_backup_dir(src)
    assert backup.parent == src.parent
    assert backup.name == "Documents_originals"


# ---------------------------------------------------------------- task list
def test_pdf_goes_next_to_the_original_and_the_original_to_backup(
        tmp_path: Path):
    src = tmp_path / "Docs"
    (src / "Plant" / "deeper").mkdir(parents=True)
    tif = make_multipage_tif(src / "Plant" / "deeper" / "drawing.tif", pages=2)
    backup = tmp_path / "Docs_originals"

    summary = scan_in_place(src, backup, Options())

    assert len(summary.tasks) == 1
    task = summary.tasks[0]
    assert task.source == tif
    assert task.output == tif.parent / "drawing_from_tif.pdf"
    assert task.backup == backup / "Plant" / "deeper" / "drawing.tif"


def test_pdfs_stay_and_word_powerpoint_follow_the_switch(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "ready.pdf").write_bytes(b"%PDF-1.4\n")
    make_docx(src / "spec.docx")
    (src / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    (src / "slides.pptx").write_bytes(b"PK\x03\x04")
    make_txt(src / "notes.txt")

    everything = scan_in_place(src, tmp_path / "backup", Options())
    assert {t.source.name for t in everything.tasks} == \
        {"spec.docx", "old.doc", "slides.pptx", "notes.txt"}
    assert everything.skipped_accepted == 1          # the PDF is never touched

    kept = scan_in_place(src, tmp_path / "backup",
                         Options(convert_accepted=False))
    assert {t.source.name for t in kept.tasks} == {"notes.txt"}
    assert kept.skipped_accepted == 4


def test_the_backup_folder_is_not_scanned_again(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "first.txt")
    backup = src / "originals"
    (backup / "old").mkdir(parents=True)
    make_txt(backup / "old" / "earlier.txt")

    summary = scan_in_place(src, backup, Options())
    assert [t.source.name for t in summary.tasks] == ["first.txt"]


def test_a_rerun_does_not_convert_again(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "data.txt")
    backup = tmp_path / "backup"

    _run(scan_in_place(src, backup, Options()).tasks)
    assert scan_in_place(src, backup, Options()).tasks == []

    # Even with the original put back, it is not converted twice.
    make_txt(src / "data.txt")
    third = scan_in_place(src, backup, Options())
    assert third.tasks == [] and third.skipped_already_done == 1


# ----------------------------------------------------------------- execution
def test_full_in_place_run_moves_the_originals(tmp_path: Path):
    src = tmp_path / "Docs"
    (src / "Plant A" / "Drawings").mkdir(parents=True)
    make_multipage_tif(src / "Plant A" / "Drawings" / "plan.tif", pages=2)
    make_xlsx(src / "Plant A" / "parts.xlsx", sheets=1, with_empty=False)
    make_csv(src / "list.csv")
    backup = tmp_path / "Docs_originals"

    results = _run(scan_in_place(src, backup, Options()).tasks)

    assert all(r.status is Status.SUCCESS for r in results), \
        [(r.source.name, r.message) for r in results if not r.ok]
    for rel in ("Plant A/Drawings/plan_from_tif.pdf",
                "Plant A/parts_from_xlsx.pdf", "list_from_csv.pdf"):
        assert_valid_pdf(src / rel)
    for rel in ("Plant A/Drawings/plan.tif", "Plant A/parts.xlsx",
                "list.csv"):
        assert (backup / rel).exists(), f"not in the backup: {rel}"
        assert not (src / rel).exists(), f"original left in place: {rel}"
    assert _leftovers(src) == []
    assert HUN in pdf_text(src / "Plant A" / "parts_from_xlsx.pdf")


def test_an_existing_pdf_of_the_same_name_is_not_overwritten(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    make_multipage_tif(src / "SAFETY.tif", pages=1)
    original_pdf = src / "SAFETY.pdf"
    original_pdf.write_bytes(b"%PDF-1.4\n% untouchable\n")

    results = _run(scan_in_place(src, tmp_path / "backup", Options()).tasks)

    assert all(r.status is Status.SUCCESS for r in results)
    assert original_pdf.read_bytes() == b"%PDF-1.4\n% untouchable\n"
    assert_valid_pdf(src / "SAFETY_from_tif.pdf")


def test_a_failed_conversion_leaves_the_original_alone(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    bad = src / "broken.tif"
    bad.write_bytes(b"not an image")
    backup = tmp_path / "backup"

    results = _run(scan_in_place(src, backup, Options()).tasks)

    assert results[0].status is Status.FAILED
    assert results[0].output is None
    assert bad.exists()
    assert not (backup / "broken.tif").exists()
    assert not (src / "broken_from_tif.pdf").exists()
    assert _leftovers(src) == []


def test_if_the_original_cannot_move_the_pdf_is_withdrawn(tmp_path: Path,
                                                         monkeypatch):
    """Otherwise a re-run would skip the file forever."""
    import cornverter.engine as engine

    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "data.txt")
    backup = tmp_path / "backup"

    def boom(source, dest):
        raise OSError("the file is held by another program")

    monkeypatch.setattr(engine, "move_original", boom)
    results = _run(scan_in_place(src, backup, Options()).tasks)

    assert results[0].status is Status.FAILED
    assert "backup" in results[0].message
    assert not (src / "data_from_txt.pdf").exists()
    assert (src / "data.txt").exists()
    assert _leftovers(src) == []

    monkeypatch.undo()
    assert len(scan_in_place(src, backup, Options()).tasks) == 1


def test_a_backup_name_collision_gets_a_timestamp(tmp_path: Path):
    src = make_txt(tmp_path / "a.txt")
    dest = tmp_path / "backup" / "a.txt"
    dest.parent.mkdir(parents=True)
    dest.write_text("already here", encoding="utf-8")

    moved = move_original(src, dest)

    assert moved != dest
    assert moved.name.startswith("a_") and moved.suffix == ".txt"
    assert dest.read_text(encoding="utf-8") == "already here"
    assert moved.exists()


# ---------------------------------------------------------------- long paths
def _deep_tree(root: Path, depth: int = 5) -> Path:
    """A folder deeper than 260 characters."""
    deep = root
    for i in range(depth):
        deep = deep / f"a_very_long_folder_name_{i}_{'x' * 30}"
    os.makedirs(long_path(deep), exist_ok=True)
    return deep


def test_scan_and_conversion_work_on_long_paths(tmp_path: Path):
    src = tmp_path / "in"
    deep = _deep_tree(src)
    assert len(str(deep)) > 260
    target = deep / "manual.txt"
    with open(long_path(target), "wb") as f:
        f.write(f"{HUN}\nlong path test\n".encode("utf-8"))
    backup = tmp_path / "backup"

    summary = scan_in_place(src, backup, Options())
    assert len(summary.tasks) == 1, "the long-path file was not listed"
    results = _run(summary.tasks)
    assert results[0].status is Status.SUCCESS, results[0].message

    pdf = deep / "manual_from_txt.pdf"
    with open(long_path(pdf), "rb") as f:
        assert f.read(5) == b"%PDF-"
    assert not os.path.exists(long_path(target))
    assert os.path.exists(long_path(backup / target.relative_to(src)))
    assert not str(results[0].source).startswith("\\\\?\\")


def test_the_walk_reports_sizes_and_skips_the_excluded_folder(tmp_path: Path):
    from cornverter.converters.base import walk_entries

    root = tmp_path / "in"
    (root / "sub").mkdir(parents=True)
    make_txt(root / "a.txt", "12345")
    make_txt(root / "sub" / "b.txt", "1234567890")
    excluded = root / "backup"
    (excluded / "deeper").mkdir(parents=True)
    make_txt(excluded / "not_this.txt")
    make_txt(excluded / "deeper" / "nor_this.txt")

    entries = dict(walk_entries(root, exclude=excluded))

    assert sorted(p.name for p in entries) == ["a.txt", "b.txt"]
    assert entries[root / "a.txt"] == 5
    assert entries[root / "sub" / "b.txt"] == 10


def test_the_walk_handles_a_long_tree(tmp_path: Path):
    deep = _deep_tree(tmp_path / "in", depth=6)
    for name in ("a.txt", "b.tif"):
        with open(long_path(deep / name), "wb") as f:
            f.write(b"x")

    found = sorted(p.name for p in walk_files(tmp_path / "in"))
    assert found == ["a.txt", "b.tif"]
    assert all(p == plain_path(p) for p in walk_files(tmp_path / "in"))
