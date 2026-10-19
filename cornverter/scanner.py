"""
Recursive folder scan that builds the task list.

Two modes:

* **Separate output folder** (`scan`) - the PDFs go into another folder that
  mirrors the input tree. The originals are not touched.
* **In place** (`scan_in_place`) - the PDF is written NEXT TO the original as
  `<name>_from_<ext>.pdf`, and the original moves into a backup folder,
  keeping its relative path. One run leaves the input folder in a
  "PDF-only" state while every original stays restorable.

The `_from_<ext>` suffix is deliberate: it can never collide with a PDF of
the same name that is already there (common in mixed folders), and the name
tells what the PDF was made from.

`validate_paths` must accept the folder pair before either scan runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .converters import Options
from .converters.base import (
    categorize,
    human_size,
    is_inside,
    long_path,
    real_key,
    walk_entries,
)

# The name of a PDF made in place is built with this marker.
FROM_MARKER = "_from_"

# Default name of the backup folder: "<input folder>_originals".
BACKUP_SUFFIX = "_originals"


@dataclass
class Task:
    """One file to convert, with its output path.

    `backup` is set only in in-place mode: the original moves there once the
    conversion has succeeded.
    """

    source: Path
    output: Path
    category: str
    size: int
    backup: Path | None = None


@dataclass
class ScanSummary:
    total_files: int = 0
    tasks: list[Task] = field(default_factory=list)
    skipped_accepted: int = 0
    skipped_junk: int = 0
    skipped_by_option: int = 0
    skipped_already_done: int = 0
    skipped_existing: int = 0
    skipped_links: list[Path] = field(default_factory=list)
    unknown: int = 0
    by_category: dict = field(default_factory=dict)
    total_bytes_to_convert: int = 0

    def human_total(self) -> str:
        return human_size(self.total_bytes_to_convert)

    @property
    def skipped_total(self) -> int:
        return (self.skipped_accepted + self.skipped_by_option
                + self.skipped_already_done + self.skipped_existing)


def validate_paths(input_dir: Path | str, second_dir: Path | str,
                   in_place: bool) -> str | None:
    """Check the folder pair before scanning. Returns an error text or None.

    Refused, because each one could overwrite or scramble the user's files:

    * the output/backup folder is the input folder itself,
    * the output/backup folder contains the input folder,
    * the output/backup path is an existing file.

    A folder INSIDE the input is fine - the scan never enters it.
    """
    role = "backup folder" if in_place else "output folder"
    if not str(input_dir).strip() or not os.path.isdir(long_path(input_dir)):
        return "The input folder does not exist."
    if not str(second_dir).strip():
        return f"Choose a {role}."
    if os.path.exists(long_path(second_dir)) \
            and not os.path.isdir(long_path(second_dir)):
        return f"The {role} is an existing file, not a folder."
    input_key, second_key = real_key(input_dir), real_key(second_dir)
    if input_key == second_key:
        return f"The {role} cannot be the input folder itself."
    if is_inside(input_key, second_key):
        return f"The {role} cannot be a parent of the input folder."
    return None


def converted_name(src: Path) -> str:
    """Name of a PDF made in place: `report.xls` -> `report_from_xls.pdf`."""
    ext = src.suffix.lstrip(".").lower() or "file"
    return f"{src.stem}{FROM_MARKER}{ext}.pdf"


def _should_convert(cat: str, opts: Options) -> bool:
    """Whether the current options convert this category.

    "text" and "office" are the core job and have no switch; the rest can be
    turned off in the GUI.
    """
    if cat in ("text", "office"):
        return True
    if cat == "msg":
        return opts.convert_msg
    if cat == "image":
        return opts.convert_images
    if cat == "archive":
        return opts.expand_archives
    if cat == "accepted":
        return opts.convert_accepted
    return False


def _admit(src: Path, summary: ScanSummary, opts: Options,
           in_place: bool) -> str | None:
    """Count one file and return its category if it should be converted."""
    summary.total_files += 1
    cat = categorize(src)
    summary.by_category[cat] = summary.by_category.get(cat, 0) + 1

    if cat == "junk":
        summary.skipped_junk += 1
        return None
    if cat == "unknown":
        summary.unknown += 1
        return None
    # PDF / Word / PowerPoint files follow one switch in both modes; an
    # existing PDF is never touched in place.
    if cat == "accepted" and (not opts.convert_accepted or (
            in_place and src.suffix.lower() == ".pdf")):
        summary.skipped_accepted += 1
        return None
    if _is_excel(src) and not opts.convert_excel:
        summary.skipped_by_option += 1
        return None
    if cat != "accepted" and not _should_convert(cat, opts):
        summary.skipped_by_option += 1
        return None
    return cat


def _excluded_root(input_dir: Path, other: Path | None) -> Path | None:
    """The folder INSIDE the input that the walk must leave out.

    That is the output or the backup folder: otherwise our own PDFs and the
    moved originals would be read in again.
    """
    if other is None:
        return None
    try:
        if is_inside(real_key(other), real_key(input_dir)):
            return other
    except (OSError, ValueError):
        return None
    return None


def _output_names(input_dir: Path, output_dir: Path,
                  sources: list[Path]) -> list[Path]:
    """Output path per source (separate output folder mode).

    `<stem>.pdf`, or `<stem>_<ext>.pdf` for every file whose folder holds
    another convertible file with the same stem (`report.txt` and
    `report.xlsx` would otherwise both become `report.pdf`). The rule depends
    only on the set of files, never on the walk order, so the names are
    deterministic; a counter is the last resort.
    """
    def key(src: Path) -> tuple[str, str]:
        return str(src.parent).lower(), src.stem.lower()

    stems: dict[tuple[str, str], int] = {}
    for src in sources:
        stems[key(src)] = stems.get(key(src), 0) + 1

    taken: set[str] = set()
    names: list[Path] = []
    for src in sources:
        folder = output_dir / src.parent.relative_to(input_dir)
        name = src.stem
        if stems[key(src)] > 1:
            name += "_" + (src.suffix.lstrip(".").lower() or "file")
        final, n = folder / f"{name}.pdf", 2
        while str(final).lower() in taken:
            final, n = folder / f"{name}_{n}.pdf", n + 1
        taken.add(str(final).lower())
        names.append(final)
    return names


def scan(input_dir: Path, output_dir: Path, opts: Options) -> ScanSummary:
    """Task list for a separate output folder (the originals stay put)."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    summary = ScanSummary()
    exclude = _excluded_root(input_dir, output_dir)

    admitted: list[tuple[Path, int, str]] = []
    for src, size in walk_entries(input_dir, exclude, summary.skipped_links):
        cat = _admit(src, summary, opts, in_place=False)
        if cat is not None:
            admitted.append((src, size, cat))

    names = _output_names(input_dir, output_dir, [a[0] for a in admitted])
    for (src, size, cat), out_path in zip(admitted, names):
        if not opts.overwrite and _exists(out_path):
            # Never replace an existing file silently (overwrite is opt-in).
            summary.skipped_existing += 1
            continue
        summary.tasks.append(Task(source=src, output=out_path,
                                  category=cat, size=size))
        summary.total_bytes_to_convert += size

    return summary


def scan_in_place(input_dir: Path, backup_dir: Path,
                  opts: Options) -> ScanSummary:
    """Task list for in-place conversion.

    The PDF goes next to the original as `<name>_from_<ext>.pdf`, the original
    into `backup_dir`, keeping its relative path.
    """
    input_dir = Path(input_dir)
    backup_dir = Path(backup_dir)
    summary = ScanSummary()
    exclude = _excluded_root(input_dir, backup_dir)

    for src, size in walk_entries(input_dir, exclude, summary.skipped_links):
        cat = _admit(src, summary, opts, in_place=True)
        if cat is None:
            continue
        out_path = src.parent / converted_name(src)
        if _exists(out_path):
            # An earlier run already made it - re-running is harmless.
            summary.skipped_already_done += 1
            continue
        rel = src.relative_to(input_dir)
        summary.tasks.append(Task(
            source=src, output=out_path, category=cat,
            size=size, backup=backup_dir / rel,
        ))
        summary.total_bytes_to_convert += size

    return summary


def default_backup_dir(input_dir: Path) -> Path:
    """Default backup folder, next to the input folder."""
    input_dir = Path(input_dir)
    return input_dir.parent / f"{input_dir.name}{BACKUP_SUFFIX}"


def _is_excel(src: Path) -> bool:
    return src.suffix.lower() in (".xlsx", ".xls", ".xlsm", ".xlsb", ".ods")


def _exists(path: Path) -> bool:
    return os.path.exists(long_path(path))
