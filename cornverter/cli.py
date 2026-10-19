"""
Command line: the same engine as the GUI, without Qt.

    python main.py <file-or-folder> [--out DIR] [--inplace [--backup DIR]]

* a file  -> `<name>.pdf` next to it (or in --out); never overwrites;
* a folder -> PDFs in `<folder>_PDF` next to it (or --out), mirroring the
  tree, plus a report; with --inplace the PDF goes next to each original
  and the original moves to `<folder>_originals` (or --backup).

Exit code: 0 = everything converted or skipped on purpose, 1 = at least one
file failed, 2 = invalid arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __app_name__, __version__
from .converters import Options
from .converters.base import ConversionResult, Status, reset_cancel
from .engine import RunOutcome, run_tasks, single_file_tasks, write_reports
from .scanner import default_backup_dir, scan, scan_in_place, validate_paths

_TAG = {Status.SUCCESS: "OK", Status.FAILED: "FAIL", Status.SKIPPED: "SKIP",
        Status.UNSUPPORTED: "N/A"}


def _print_result(result: ConversionResult, done: int, total: int) -> None:
    target = f" -> {result.output}" if result.output else ""
    note = f"  ({result.message})" if result.message else ""
    print(f"[{done}/{total}] {_TAG.get(result.status, '?'):4} "
          f"{result.source.name}{target}{note}", flush=True)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cornverter",
        description="Convert a file, or a folder of mixed files, to PDF "
                    "(no window).")
    p.add_argument("path", help="a file, or a folder of mixed files")
    p.add_argument("--out", metavar="DIR",
                   help="output folder (default: next to the file, or "
                        "<folder>_PDF next to the folder)")
    p.add_argument("--inplace", action="store_true",
                   help="folder only: PDF next to each original, the "
                        "originals move to a backup folder")
    p.add_argument("--backup", metavar="DIR",
                   help="with --inplace: the backup folder (default: "
                        "<folder>_originals)")
    p.add_argument("--overwrite", action="store_true",
                   help="replace PDFs that already exist in the output folder")
    p.add_argument("--version", action="version",
                   version=f"{__app_name__} {__version__}")
    return p


def _failed(outcome: RunOutcome) -> bool:
    return any(r.status is Status.FAILED for r in outcome.results)


def _run_file(path: Path, out: Path | None) -> int:
    tasks, already_pdf = single_file_tasks([path], out)
    for pdf in already_pdf:
        print(f"SKIP {pdf.name} (already a PDF)")
    outcome = run_tasks(tasks, Options(), on_result=_print_result)
    return 1 if _failed(outcome) else 0


def _run_folder(parser: argparse.ArgumentParser, folder: Path,
                args: argparse.Namespace) -> int:
    if args.inplace:
        second = Path(args.backup) if args.backup else default_backup_dir(folder)
    else:
        second = Path(args.out) if args.out else \
            folder.parent / f"{folder.name}_PDF"
    error = validate_paths(folder, second, args.inplace)
    if error:
        parser.error(error)

    options = Options(overwrite=args.overwrite and not args.inplace)
    summary = (scan_in_place(folder, second, options) if args.inplace
               else scan(folder, second, options))
    print(f"{summary.total_files} file(s) found, {len(summary.tasks)} to "
          f"convert ({summary.human_total()}).", flush=True)
    outcome = run_tasks(summary.tasks, options, on_result=_print_result)
    report = write_reports(outcome, second, folder, second)
    print(f"Report: {report}")
    return 1 if _failed(outcome) else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = _parser()
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        parser.error(f"not found: {path}")
    if path.is_file() and (args.inplace or args.backup):
        parser.error("--inplace / --backup work on folders only")

    reset_cancel()
    try:
        if path.is_file():
            return _run_file(path, Path(args.out) if args.out else None)
        return _run_folder(parser, path, args)
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130
