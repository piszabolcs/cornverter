"""
Run reports: a CSV log (one row per file) and a Markdown summary.

Paths in the rows are relative to the input folder where possible: shorter
to read, and the report does not spell out the user's whole directory layout
when it ends up in a shared folder.
"""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from .converters.base import ConversionResult, Status

# A Markdown cell longer than this is cut (the CSV keeps the full message).
_MAX_CELL = 500


def _rel(path: Path | None, *roots: Path | str | None) -> str:
    if path is None:
        return ""
    for root in roots:
        if root:
            try:
                return Path(path).relative_to(root).as_posix()
            except ValueError:
                continue
    return str(path)


def _cell(text: object) -> str:
    """One Markdown table cell: a single line with the pipes escaped."""
    flat = " ".join(str(text).split())
    if len(flat) > _MAX_CELL:
        flat = flat[:_MAX_CELL - 1] + "…"
    return flat.replace("|", "\\|")


def write_csv(results: list[ConversionResult], out_csv: Path,
              root: Path | str | None = None) -> None:
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source_file", "status", "engine", "output",
                         "duration_s", "message"])
        for r in results:
            writer.writerow([
                _rel(r.source, root),
                r.status.value,
                r.engine,
                _rel(r.output, root, out_csv.parent),
                f"{r.duration_s:.2f}",
                r.message,
            ])


def _table(title: str, rows: list[ConversionResult],
           root: Path | str | None) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        return lines + ["None."]
    lines += ["| Source | Engine | Message |", "|---|---|---|"]
    for r in rows:
        lines.append(f"| `{_cell(_rel(r.source, root))}` | {_cell(r.engine)} "
                     f"| {_cell(r.message)} |")
    return lines


def write_markdown(results: list[ConversionResult], out_md: Path,
                   input_dir: str = "", output_dir: str = "",
                   root: Path | str | None = None) -> None:
    out_md = Path(out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    def count(status: Status) -> int:
        return sum(1 for r in results if r.status is status)

    cancelled = count(Status.CANCELLED)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# CornVerter conversion report",
        "",
        f"Created: {now}  ",
        f"Input folder: `{input_dir}`  ",
        f"Output folder: `{output_dir}`",
    ]
    if cancelled:
        lines += ["", f"> The run was cancelled: {cancelled} file(s) were "
                      f"not processed."]
    lines += [
        "",
        "## Summary",
        "",
        f"- Items: {len(results)}",
        f"- Converted: {count(Status.SUCCESS)}",
        f"- Failed: {count(Status.FAILED)}",
        f"- Skipped: {count(Status.SKIPPED)}",
        f"- Unsupported: {count(Status.UNSUPPORTED)}",
        f"- Cancelled: {cancelled}",
        f"- Total processing time: "
        f"{sum(r.duration_s for r in results):.1f} s",
    ]
    lines += _table("Failed items",
                    [r for r in results if r.status is Status.FAILED], root)
    lines += _table("Skipped items",
                    [r for r in results
                     if r.status in (Status.SKIPPED, Status.UNSUPPORTED)],
                    root)

    lines += ["", "## Engines used", ""]
    by_engine: dict[str, int] = {}
    for r in results:
        if r.status is Status.SUCCESS:
            key = r.engine.split(" ")[0]
            by_engine[key] = by_engine.get(key, 0) + 1
    if by_engine:
        lines += ["| Engine | Converted |", "|---|---|"]
        for name, n in sorted(by_engine.items(), key=lambda x: -x[1]):
            lines.append(f"| {_cell(name)} | {n} |")
    else:
        lines.append("No successful conversion.")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
