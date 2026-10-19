"""
Headless job engine: runs tasks with atomic writes and safe backups.

There is no Qt here - the GUI worker thread and the command line both drive
this module. The order of file operations for one task (`execute_task`):

  1. the converter writes into a `.cvtmp` work file,
  2. only a verified PDF (pypdf opens it and finds at least one page) is
     moved onto its final name (an atomic replace on the same volume),
  3. and only then does the original move to the backup folder (in place).

If step 3 fails (another program holds the file, say), the finished PDF is
withdrawn too. Otherwise the next run would see "already done" and the
original would never reach the backup.
"""

from __future__ import annotations

import datetime as _dt
import errno
import itertools
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .converters import Options, convert_file
from .converters.base import (
    ConversionResult,
    Status,
    cancel_requested,
    categorize,
    long_path,
    plain_path,
)
from .report import write_csv, write_markdown
from .scanner import Task

# Suffix of the work file a conversion writes into.
TMP_SUFFIX = ".cvtmp"

# Win32 ERROR_NOT_SAME_DEVICE: a rename cannot cross volumes.
_WIN_NOT_SAME_DEVICE = 17


@dataclass
class RunOutcome:
    """Results of a run, plus the tasks a cancel left unprocessed."""

    results: list[ConversionResult] = field(default_factory=list)
    cancelled: list[Task] = field(default_factory=list)


def _is_real_pdf(path: Path) -> bool:
    """A readable PDF with at least one page - not just a %PDF- header."""
    try:
        from pypdf import PdfReader

        with open(long_path(path), "rb") as f:
            if f.read(5) != b"%PDF-":
                return False
            f.seek(0)
            return len(PdfReader(f).pages) >= 1
    except Exception:  # noqa: BLE001 - unreadable means invalid
        return False


def _backup_destination(dest: Path) -> Path:
    """Collision-free backup path (if a file of that name is already there)."""
    if not os.path.exists(long_path(dest)):
        return dest
    return dest.with_name(f"{dest.stem}_{int(time.time())}{dest.suffix}")


def _cross_volume(exc: OSError) -> bool:
    return (exc.errno == errno.EXDEV
            or getattr(exc, "winerror", None) == _WIN_NOT_SAME_DEVICE)


def move_original(source: Path, dest: Path) -> Path:
    """Move the original into the backup folder, creating folders as needed.

    A rename comes first: it is atomic on one volume, and a locked file makes
    it fail cleanly. Only across volumes is the file copied - and if the
    source then cannot be removed, the copy is withdrawn, so no stray
    duplicate is left in the backup.
    """
    os.makedirs(long_path(dest.parent), exist_ok=True)
    final = _backup_destination(dest)
    try:
        os.rename(long_path(source), long_path(final))
        return final
    except OSError as exc:
        if not _cross_volume(exc):
            raise
    shutil.copy2(long_path(source), long_path(final))
    try:
        os.remove(long_path(source))
    except OSError:
        _discard(final)
        raise
    return final


def _discard(path: Path) -> None:
    try:
        os.remove(long_path(path))
    except OSError:
        pass


def _skip(task: Task, message: str) -> ConversionResult:
    return ConversionResult(source=task.source, status=Status.SKIPPED,
                            message=message, engine="worker")


def execute_task(task: Task, options: Options) -> ConversionResult:
    """Run one task with an atomic write and a safe backup move.

    Never raises: an unexpected error becomes a FAILED result, so one bad file
    cannot stop a run (or leave the GUI waiting forever).
    """
    try:
        return _execute(task, options)
    except Exception as exc:  # noqa: BLE001
        return ConversionResult(source=task.source, status=Status.FAILED,
                                message=f"Unexpected error: {exc}",
                                engine="worker")


def _execute(task: Task, options: Options) -> ConversionResult:
    if not options.overwrite and os.path.exists(long_path(task.output)):
        # Checked again here: the file may have appeared after the scan.
        return _skip(task, "A file with the target name already exists - "
                           "left untouched (overwriting is off).")
    if os.path.getsize(long_path(task.source)) == 0:
        return _skip(task, "Empty file (0 bytes) - nothing to convert.")

    tmp = task.output.with_name(task.output.name + TMP_SUFFIX)
    os.makedirs(long_path(task.output.parent), exist_ok=True)
    _discard(tmp)  # a work file left behind by an interrupted run

    try:
        result = convert_file(long_path(task.source), long_path(tmp), options)
    except Exception as exc:  # noqa: BLE001
        _discard(tmp)
        return ConversionResult(source=task.source, status=Status.FAILED,
                                message=f"Unexpected error: {exc}",
                                engine="worker")

    # The converters work with prefixed paths - reports need readable ones.
    result.source = plain_path(result.source)

    if result.status is not Status.SUCCESS:
        _discard(tmp)
        result.output = None
        return result

    if not _is_real_pdf(tmp):
        _discard(tmp)
        result.status = Status.FAILED
        result.output = None
        result.message = ("The conversion ran but produced no valid PDF. "
                          f"{result.message}").strip()
        return result

    try:
        os.replace(long_path(tmp), long_path(task.output))
    except OSError as exc:
        _discard(tmp)
        result.status = Status.FAILED
        result.output = None
        result.message = f"The finished PDF could not be put in place: {exc}"
        return result

    result.output = task.output
    if task.backup is not None:
        _move_to_backup(task, result)
    return result


def _move_to_backup(task: Task, result: ConversionResult) -> None:
    try:
        moved = move_original(task.source, task.backup)
    except OSError as exc:
        # The original could not be moved: withdraw the PDF as well, so the
        # next run tries this file again.
        _discard(task.output)
        result.status = Status.FAILED
        result.output = None
        result.message = (
            f"The PDF was made, but the original could not be moved to the "
            f"backup folder ({exc}). The PDF was withdrawn so a re-run can "
            f"fix it - close the file in other programs.")
        return
    note = f"Original moved to backup: {plain_path(moved).name}"
    result.message = f"{result.message} {note}".strip()


def run_tasks(tasks: list[Task], options: Options,
              on_start: Optional[Callable[[Task], None]] = None,
              on_result: Optional[Callable[[ConversionResult, int, int],
                                           None]] = None,
              outcome: Optional[RunOutcome] = None) -> RunOutcome:
    """Run the tasks in order until done or cancelled.

    `outcome` may be passed in so a caller keeps the partial results even if
    one of its callbacks raises.
    """
    outcome = outcome if outcome is not None else RunOutcome()
    total = len(tasks)
    for i, task in enumerate(tasks):
        if cancel_requested():
            outcome.cancelled = list(tasks[i:])
            break
        if on_start is not None:
            on_start(task)
        result = execute_task(task, options)
        outcome.results.append(result)
        if on_result is not None:
            on_result(result, i + 1, total)
    return outcome


def write_reports(outcome: RunOutcome, report_dir: Path, input_dir: Path,
                  output_dir: Path) -> Path:
    """Write the CSV log and the Markdown summary; returns the Markdown path.

    The names carry a timestamp, so a later run never overwrites the report
    of an earlier one.
    """
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = Path(report_dir) / f"cornverter_report_{stamp}.csv"
    md_path = Path(report_dir) / f"cornverter_report_{stamp}.md"
    results = outcome.results + [
        ConversionResult(source=t.source, status=Status.CANCELLED,
                         message="Not processed - the run was cancelled.")
        for t in outcome.cancelled
    ]
    write_csv(results, csv_path, root=input_dir)
    write_markdown(results, md_path, input_dir=str(input_dir),
                   output_dir=str(output_dir), root=input_dir)
    return md_path


def single_file_tasks(files: list[Path], out_dir: Optional[Path] = None
                      ) -> tuple[list[Task], list[Path]]:
    """Tasks for single files (quick mode): `<name>.pdf` next to each file,
    or in `out_dir` when given.

    An existing file is never overwritten: the name falls back to
    `<name>_from_<ext>.pdf`, then gets a counter. Returns (tasks, PDFs left
    out because they would only be copied next to themselves).
    """
    tasks: list[Task] = []
    already_pdf: list[Path] = []
    taken: set[str] = set()
    for src in map(Path, files):
        if out_dir is None and src.suffix.lower() == ".pdf":
            already_pdf.append(src)
            continue
        folder = Path(out_dir) if out_dir is not None else src.parent
        ext = src.suffix.lstrip(".").lower() or "file"
        names = itertools.chain(
            [f"{src.stem}.pdf", f"{src.stem}_from_{ext}.pdf"],
            (f"{src.stem}_from_{ext}_{n}.pdf" for n in itertools.count(2)))
        for name in names:
            target = folder / name
            if (str(target).lower() not in taken
                    and not os.path.exists(long_path(target))):
                break
        taken.add(str(target).lower())
        tasks.append(Task(source=src, output=target, category=categorize(src),
                          size=os.path.getsize(long_path(src))))
    return tasks, already_pdf
