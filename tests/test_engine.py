"""Engine: one bad task never stops a run, and a failed move leaves no debris."""

from __future__ import annotations

from pathlib import Path

from conftest import make_txt

from cornverter.converters import Options
from cornverter.converters.base import Status
from cornverter.engine import execute_task, run_tasks
from cornverter.scanner import scan, scan_in_place


def test_an_unexpected_error_fails_one_task_and_the_run_goes_on(tmp_path: Path):
    src = tmp_path / "in"
    (src / "apple").mkdir(parents=True)
    make_txt(src / "apple" / "inner.txt")
    make_txt(src / "zeta.txt")
    out = tmp_path / "out"
    out.mkdir()
    (out / "apple").write_bytes(b"a FILE where a folder is needed")

    outcome = run_tasks(scan(src, out, Options()).tasks, Options())

    by_name = {r.source.name: r for r in outcome.results}
    assert by_name["zeta.txt"].status is Status.SUCCESS
    assert by_name["inner.txt"].status is Status.FAILED
    assert "Unexpected error" in by_name["inner.txt"].message


def test_a_locked_original_leaves_no_copy_in_the_backup(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    original = make_txt(src / "locked.txt")
    backup = tmp_path / "backup"
    task = scan_in_place(src, backup, Options()).tasks[0]

    with open(original, "rb"):            # held open: Windows refuses the move
        result = execute_task(task, Options())

    assert result.status is Status.FAILED
    assert original.exists()
    assert not (src / "locked_from_txt.pdf").exists()
    assert not list(backup.rglob("*.txt")), "a stray copy was left behind"

    again = execute_task(scan_in_place(src, backup, Options()).tasks[0],
                         Options())
    assert again.status is Status.SUCCESS
    assert [p.name for p in backup.iterdir()] == ["locked.txt"]


def test_an_empty_source_is_skipped_and_stays_in_place(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    empty = src / "empty.xlsx"
    empty.write_bytes(b"")
    backup = tmp_path / "backup"

    result = execute_task(scan_in_place(src, backup, Options()).tasks[0],
                          Options())

    assert result.status is Status.SKIPPED
    assert "Empty file" in result.message
    assert empty.exists() and not backup.exists()
