"""
Shared types and helpers for the converters.

This module does not depend on PySide6, so everything built on it runs
headless: from the command line, in tests and in the GUI worker thread.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class Status(str, Enum):
    """Final state of one file's conversion."""

    SUCCESS = "success"          # a PDF was produced
    SKIPPED = "skipped"          # deliberately left out (junk, password, limit...)
    FAILED = "failed"            # an error happened during the conversion
    UNSUPPORTED = "unsupported"  # there is no converter for this type
    CANCELLED = "cancelled"      # not processed: the run was cancelled


@dataclass
class ConversionResult:
    """Outcome of processing one input file."""

    source: Path
    status: Status
    output: Optional[Path] = None
    message: str = ""
    engine: str = ""
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is Status.SUCCESS


# ---------------------------------------------------------------------------
# Long paths (Windows MAX_PATH)
# ---------------------------------------------------------------------------

# The classic Win32 file APIs limit a path to 260 characters unless the
# LongPathsEnabled policy is switched on (it is off by default). Deep document
# trees exceed that easily - more so once the "_from_<ext>" suffix and the
# backup folder name are added - and the failure is a misleading "path not
# found" (WinError 3), already while walking the tree, not only when writing.
#
# The \\?\ prefix (extended-length path) lifts the limit. It is added only at
# the moment of a file operation; stored and displayed paths stay readable
# (see `plain_path`).
LONG_PREFIX = "\\\\?\\"
_UNC_LONG_PREFIX = LONG_PREFIX + "UNC\\"


def long_path(path: Path | str) -> Path:
    r"""Absolute path with the \\?\ prefix (on Windows)."""
    if os.name != "nt":
        return Path(path)
    text = str(path)
    if text.startswith(LONG_PREFIX):
        return Path(text)
    text = os.path.abspath(text)
    if text.startswith("\\\\"):  # UNC: \\host\share -> \\?\UNC\host\share
        return Path(_UNC_LONG_PREFIX + text[2:])
    return Path(LONG_PREFIX + text)


def plain_path(path: Path | str) -> Path:
    r"""Strip the \\?\ prefix so it never shows up in logs and reports."""
    text = str(path)
    if text.startswith(_UNC_LONG_PREFIX):
        return Path("\\\\" + text[len(_UNC_LONG_PREFIX):])
    if text.startswith(LONG_PREFIX):
        return Path(text[len(LONG_PREFIX):])
    return Path(text)


def real_key(path: Path | str) -> str:
    """Comparison key of the fully resolved path (links and junctions resolved)."""
    resolved = os.path.realpath(long_path(path))
    return os.path.normcase(str(plain_path(resolved)))


def is_inside(child_key: str, parent_key: str) -> bool:
    """True if `child_key` equals or lies below `parent_key` (see `real_key`)."""
    try:
        return os.path.commonpath([child_key, parent_key]) == parent_key
    except ValueError:  # different drives
        return False


def _is_link(entry: os.DirEntry) -> bool:
    """Symbolic link or NTFS junction (directory mount point)."""
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)  # Python 3.12+
        return bool(is_junction and is_junction())
    except OSError:
        return True  # unreadable entry: treat it as unsafe and leave it out


def walk_entries(root: Path, exclude: Path | None = None,
                 skipped_links: list[Path] | None = None):
    """Yield (path, size) pairs recursively, quickly and without following links.

    Why not `Path.rglob` or `os.walk` + `stat`:

    * `rglob` breaks on sub-folders beyond 260 characters, so the walk starts
      from the prefixed root (the yielded paths are prefix-free);
    * `os.scandir` returns the size with the directory listing almost for
      free, a separate `os.stat` per file costs another disk round trip;
    * the excluded folder (output / backup) is not entered at all.

    Symbolic links and junctions are never followed: they can point outside
    the chosen folder (files there would be converted and, in in-place mode,
    moved) or form loops. They are collected in `skipped_links` so the caller
    can report them. As a second line of defence every directory must resolve
    to a location inside the root.
    """
    exclude_key = real_key(exclude) if exclude is not None else None
    root_key = real_key(root)

    def skip(entry: os.DirEntry) -> None:
        if skipped_links is not None:
            skipped_links.append(plain_path(entry.path))

    def walk(directory: Path):
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        dirs: list[Path] = []
        for entry in entries:
            if _is_link(entry):
                skip(entry)
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                dir_key = real_key(entry.path)
                if dir_key == exclude_key:
                    continue
                if not is_inside(dir_key, root_key):
                    skip(entry)
                    continue
                dirs.append(Path(entry.path))
                continue
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
            yield plain_path(entry.path), size
        for sub in dirs:
            yield from walk(sub)

    yield from walk(long_path(root))


def walk_files(root: Path, exclude: Path | None = None):
    """Paths only (see `walk_entries`)."""
    for path, _size in walk_entries(root, exclude):
        yield path


# ---------------------------------------------------------------------------
# LibreOffice discovery (Windows + Linux + macOS)
# ---------------------------------------------------------------------------

_SOFFICE_CACHE: Optional[str] = None


def find_soffice() -> Optional[str]:
    """Locate the LibreOffice executable. The result is cached."""
    global _SOFFICE_CACHE
    if _SOFFICE_CACHE is not None:
        return _SOFFICE_CACHE or None

    # 1) Names on PATH
    for name in ("soffice", "libreoffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            _SOFFICE_CACHE = found
            return found

    # 2) Typical install locations
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for c in candidates:
        if os.path.isfile(c):
            _SOFFICE_CACHE = c
            return c

    _SOFFICE_CACHE = ""
    return None


def soffice_available() -> bool:
    return find_soffice() is not None


# ---------------------------------------------------------------------------
# LibreOffice invocation
# ---------------------------------------------------------------------------

class SofficeError(RuntimeError):
    pass


# Per-file limit for one LibreOffice call.
SOFFICE_TIMEOUT_S = 240

# LibreOffice silently fails (no output, empty stderr) when the path of its
# user profile is longer than roughly 150 characters.
MAX_PROFILE_PATH = 140

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Set by the GUI's Cancel / window close: a running LibreOffice call is killed
# within half a second and no new one is started.
_CANCEL = threading.Event()


def request_cancel() -> None:
    _CANCEL.set()


def reset_cancel() -> None:
    _CANCEL.clear()


def cancel_requested() -> bool:
    return _CANCEL.is_set()


def lo_profile_dir() -> Path:
    """The LibreOffice user profile CornVerter uses: short, fixed, reused.

    Reusing one profile saves the profile set-up on every call, and a fixed
    place under LOCALAPPDATA keeps its path short even when %TEMP% is long.
    CORNVERTER_LO_PROFILE overrides the location.
    """
    custom = os.environ.get("CORNVERTER_LO_PROFILE")
    if custom:
        return Path(custom)
    root = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return Path(root) / "CornVerter" / "lo_profile"


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill LibreOffice with its child (soffice.exe starts soffice.bin)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=30,
                       creationflags=_NO_WINDOW)
    try:
        proc.kill()
    except OSError:
        pass


def _wait(proc: subprocess.Popen, timeout: int, profile: Path,
          own_profile: bool) -> tuple[str, str]:
    """Wait for LibreOffice; kill it on timeout or cancel."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return proc.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            if _CANCEL.is_set():
                reason = "Cancelled."
            elif time.monotonic() > deadline:
                reason = f"Timed out after {timeout} s."
            else:
                continue
            _kill_tree(proc)
            proc.communicate()
            if own_profile:
                # A killed instance can leave a lock behind in the profile.
                shutil.rmtree(profile, ignore_errors=True)
            raise SofficeError(reason)


def run_soffice_convert(
    src: Path,
    out_dir: Path,
    convert_to: str = "pdf",
    filter_name: Optional[str] = None,
    timeout: int = SOFFICE_TIMEOUT_S,
    user_profile_dir: Optional[str] = None,
) -> Path:
    """Convert one file to PDF (or another format) with LibreOffice.

    LibreOffice writes the result into `out_dir` under the source name with
    the new extension. Returns the path of the produced file; every failure
    (not installed, profile path too long, timeout, cancel, no output) raises
    SofficeError with a readable reason.
    """
    soffice = find_soffice()
    if not soffice:
        raise SofficeError("LibreOffice was not found on this computer.")
    if _CANCEL.is_set():
        raise SofficeError("Cancelled.")

    profile = Path(user_profile_dir) if user_profile_dir else lo_profile_dir()
    if len(str(profile)) > MAX_PROFILE_PATH:
        raise SofficeError(
            f"The LibreOffice profile path is too long ({len(str(profile))} "
            f"characters, LibreOffice fails above ~150): {profile}. Set "
            f"CORNVERTER_LO_PROFILE to a shorter folder.")
    profile.mkdir(parents=True, exist_ok=True)

    out_dir = plain_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # LibreOffice is an external program: it does not understand the \\?\
    # prefix and cannot open paths beyond 260 characters. Such a source is
    # staged as a short-path working copy first.
    src = plain_path(src)
    staged: Optional[Path] = None
    if len(str(src)) >= 240:
        staged = out_dir / ("src_" + src.name[-60:])
        shutil.copyfile(str(long_path(src)), str(staged))
        src = staged

    target = f"{convert_to}:{filter_name}" if filter_name else convert_to
    cmd = [
        soffice,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--norestore",
        f"-env:UserInstallation={profile.as_uri()}",
        "--convert-to",
        target,
        "--outdir",
        str(out_dir),
        str(src),
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                errors="replace", creationflags=_NO_WINDOW)
        stdout, stderr = _wait(proc, timeout, profile,
                               own_profile=user_profile_dir is None)
    finally:
        if staged is not None:
            # The working copy must not be mistaken for the output.
            try:
                staged.unlink()
            except OSError:
                pass

    expected = out_dir / (src.stem + "." + convert_to)
    if expected.exists():
        return expected

    # LibreOffice sometimes uses a different name - take the newest match.
    produced = sorted(
        out_dir.glob(f"{src.stem}.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in produced:
        if p.suffix.lower() == "." + convert_to:
            return p

    detail = " | ".join(t for t in (stdout.strip(), stderr.strip()) if t)
    raise SofficeError(
        f"LibreOffice produced no output (exit code {proc.returncode})"
        + (f": {detail[:300]}" if detail else "."))


# ---------------------------------------------------------------------------
# Extension-based categories
# ---------------------------------------------------------------------------

# Formats that document stores and indexers generally accept as they are;
# by default they are not converted (the user can override this).
ALREADY_ACCEPTED = {".pdf", ".docx", ".doc", ".ppt", ".pptx"}

# Treated as junk - never converted (".cvtmp" is our own unfinished work file).
JUNK_EXT = {".tmp", ".ini", ".db", ".ds_store", ".lnk", ".url", ".bak",
            ".cvtmp"}

# Extension -> logical category (the dispatcher picks the converter by it).
EXT_CATEGORY = {
    # Spreadsheets
    ".xlsx": "office", ".xls": "office", ".xlsm": "office", ".xlsb": "office",
    ".ods": "office", ".csv": "text", ".tsv": "text",
    # Text
    ".txt": "text", ".rtf": "office", ".log": "text", ".md": "text",
    # Word / macro-enabled Word
    ".docm": "office", ".odt": "office",
    # Presentations
    ".pptm": "office", ".odp": "office",
    # E-mail
    ".msg": "msg", ".eml": "msg",
    # Images / scans
    ".tif": "image", ".tiff": "image", ".png": "image", ".jpg": "image",
    ".jpeg": "image", ".bmp": "image", ".gif": "image", ".webp": "image",
    # Archives
    ".zip": "archive", ".rar": "archive", ".7z": "archive",
    ".tar": "archive", ".gz": "archive", ".tgz": "archive",
}


def categorize(path: Path) -> str:
    """Logical category of a file for the dispatcher."""
    ext = path.suffix.lower()
    if ext in ALREADY_ACCEPTED:
        return "accepted"
    if ext in JUNK_EXT:
        return "junk"
    return EXT_CATEGORY.get(ext, "unknown")


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def xml_escape(text: str) -> str:
    """Escape text for reportlab's paragraph mini-markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def merge_pdfs(parts: list[Path], out_pdf: Path) -> tuple[int, list[str]]:
    """Concatenate `parts` into `out_pdf`.

    Returns (page count, names of the parts that could not be read). Nothing
    is written when no page could be collected: the caller reports that as a
    failure instead of producing an empty PDF.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    unreadable: list[str] = []
    for part in parts:
        try:
            writer.append(str(long_path(part)))
        except Exception:  # noqa: BLE001 - one broken part must not stop the rest
            unreadable.append(part.name)
    pages = len(writer.pages)
    if pages:
        with open(long_path(out_pdf), "wb") as f:
            writer.write(f)
    return pages, unreadable
