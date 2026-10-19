r"""
Archives: unpack, convert every inner file, merge the results into one PDF.

Handled types: .zip, .7z, .rar, .tar, .tgz / .tar.gz and plain .gz

Every inner file goes through the main dispatcher and the resulting PDFs are
concatenated, so the useful content of a package stays together and
searchable.

An archive is untrusted input, hence these rules:

* every member must land inside the extraction folder. Absolute names, drive
  letters and ".." components are refused member by member; tar members also
  pass tarfile's "data" filter (it refuses links that point outside and
  special files as well);
* limits are checked from the declared sizes BEFORE anything is written, and
  enforced again while writing: unpacked bytes, number of files and the
  unpacked/packed ratio (zip bomb);
* nested archives are expanded at most MAX_DEPTH levels deep, and all levels
  of one top-level archive share a single byte budget;
* members are written through \\?\ paths, so deep member paths work too.

Compressed .rar members need an external tool (unrar or bsdtar). Without one
the archive is skipped with a clear message rather than dropped silently.
"""

from __future__ import annotations

import contextvars
import gzip
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .base import (
    ConversionResult,
    Status,
    human_size,
    long_path,
    merge_pdfs,
    walk_entries,
)

# Safety limits. One top-level archive and everything nested in it share them.
MAX_DEPTH = 3                  # archive in an archive in an archive
MAX_TOTAL_BYTES = 1 << 30      # 1 GiB unpacked in total
MAX_MEMBERS = 5000             # files in one archive
MAX_RATIO = 100                # unpacked : packed ...
RATIO_MIN_BYTES = 10 << 20     # ... checked once more than 10 MB is unpacked

PASSWORD_MESSAGE = "Password-protected archive - skipped."

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                     *(f"COM{i}" for i in range(1, 10)),
                     *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_DRIVE = re.compile(r"^[A-Za-z]:")


class ArchiveRefused(Exception):
    """The archive breaks a safety rule or cannot be unpacked: skip it."""


@dataclass
class _Budget:
    remaining: int


@dataclass
class _Level:
    depth: int
    budget: _Budget


# Nesting depth and the shared budget of the archive being processed.
_LEVEL: contextvars.ContextVar[_Level | None] = contextvars.ContextVar(
    "cornverter_archive_level", default=None)


class _Quota:
    """Byte accounting for one archive (shared budget + ratio check)."""

    def __init__(self, packed_size: int, budget: _Budget):
        self.packed = max(packed_size, 1)
        self.budget = budget
        self.written = 0

    def check_declared(self, members: int, total: int) -> None:
        """Refuse before extraction, based on the sizes the archive declares."""
        if members > MAX_MEMBERS:
            raise ArchiveRefused(
                f"Archive refused: {members} files, the limit is {MAX_MEMBERS}.")
        if total > self.budget.remaining:
            raise ArchiveRefused(
                f"Archive refused: it would unpack to {human_size(total)}, "
                f"over the {human_size(MAX_TOTAL_BYTES)} limit.")
        self._check_ratio(total)

    def add(self, size: int) -> None:
        """Account for bytes actually written (declared sizes can lie)."""
        self.written += size
        self.budget.remaining -= size
        if self.budget.remaining < 0:
            raise ArchiveRefused(
                f"Archive refused: unpacked content exceeds the "
                f"{human_size(MAX_TOTAL_BYTES)} limit.")
        self._check_ratio(self.written)

    def _check_ratio(self, total: int) -> None:
        if total > RATIO_MIN_BYTES and total > self.packed * MAX_RATIO:
            raise ArchiveRefused(
                f"Archive refused: compression ratio {total // self.packed}:1 "
                f"looks like a zip bomb (limit {MAX_RATIO}:1).")


def member_target(dest: Path, name: str) -> Path | None:
    """Where an archive member may be written, or None if its name is unsafe."""
    name = name.replace("\\", "/")
    if name.startswith("/") or _DRIVE.match(name):
        return None
    parts: list[str] = []
    for part in name.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        part = _BAD_CHARS.sub("_", part).rstrip(" .") or "_"
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            part = "_" + part
        parts.append(part)
    return dest.joinpath(*parts) if parts else None


def _write_member(stream, target: Path, quota: _Quota) -> None:
    os.makedirs(long_path(target.parent), exist_ok=True)
    with open(long_path(target), "wb") as out:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            quota.add(len(chunk))
            out.write(chunk)


# --------------------------------------------------------------- extractors
def _extract_zip(src: Path, dest: Path, quota: _Quota) -> list[str]:
    refused: list[str] = []
    with zipfile.ZipFile(long_path(src)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if any(i.flag_bits & 0x1 for i in infos):
            raise ArchiveRefused(PASSWORD_MESSAGE)
        quota.check_declared(len(infos), sum(i.file_size for i in infos))
        for info in infos:
            target = member_target(dest, info.filename)
            if target is None:
                refused.append(info.filename)
                continue
            with z.open(info) as stream:
                _write_member(stream, target, quota)
    return refused


def _extract_tar(src: Path, dest: Path, quota: _Quota) -> list[str]:
    refused: list[str] = []
    with tarfile.open(long_path(src)) as t:
        # Links, devices and directories carry no convertible content.
        files = [m for m in t.getmembers() if m.isfile()]
        quota.check_declared(len(files), sum(m.size for m in files))
        for member in files:
            target = member_target(dest, member.name)
            if target is None:
                refused.append(member.name)
                continue
            try:
                tarfile.data_filter(member, str(dest))
            except tarfile.FilterError:
                refused.append(member.name)
                continue
            stream = t.extractfile(member)
            if stream is None:
                continue
            with stream:
                _write_member(stream, target, quota)
    return refused


def _extract_gzip(src: Path, dest: Path, quota: _Quota) -> None:
    """A plain gzipped file (not a tar.gz)."""
    target = member_target(dest, Path(src).stem) or dest / "content"
    with gzip.open(long_path(src), "rb") as stream:
        _write_member(stream, target, quota)


def _extract_7z(src: Path, dest: Path, quota: _Quota) -> list[str]:
    import py7zr

    with py7zr.SevenZipFile(long_path(src), mode="r") as z:
        if z.needs_password():
            raise ArchiveRefused(PASSWORD_MESSAGE)
        infos = [i for i in z.list() if not i.is_directory]
        if any(member_target(dest, i.filename) is None for i in infos):
            raise ArchiveRefused("Archive refused: it contains unsafe paths.")
        total = sum(i.uncompressed or 0 for i in infos)
        quota.check_declared(len(infos), total)
        z.extractall(path=dest)
    quota.add(total)
    return []


def _extract_rar(src: Path, dest: Path, quota: _Quota) -> list[str]:
    import rarfile

    with rarfile.RarFile(str(long_path(src))) as r:
        if r.needs_password():
            raise ArchiveRefused(PASSWORD_MESSAGE)
        infos = [i for i in r.infolist() if not i.is_dir()]
        if any(member_target(dest, i.filename) is None for i in infos):
            raise ArchiveRefused("Archive refused: it contains unsafe paths.")
        total = sum(i.file_size for i in infos)
        quota.check_declared(len(infos), total)
        try:
            r.extractall(path=str(dest))
        except rarfile.RarCannotExec:
            # rarfile only looks for programs NAMED unrar/bsdtar on PATH. The
            # Windows System32 tar.exe is bsdtar under another name.
            _extract_with_bsdtar(src, dest)
    quota.add(total)
    return []


@lru_cache(maxsize=1)
def find_bsdtar() -> str | None:
    """Find bsdtar, which can unpack .rar as well.

    Windows 10/11 ships a `tar.exe` in System32 that is really bsdtar
    (libarchive). On PATH, Git's GNU tar often comes first and cannot read
    .rar, so System32 is checked explicitly and the version output must say
    bsdtar.
    """
    candidates = [shutil.which("bsdtar")]
    if os.name == "nt":
        candidates.append(r"C:\Windows\System32\tar.exe")
    candidates.append(shutil.which("tar"))

    for exe in candidates:
        if not exe or not os.path.isfile(exe):
            continue
        try:
            out = subprocess.run([exe, "--version"], capture_output=True,
                                 text=True, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        if "bsdtar" in (out.stdout + out.stderr).lower():
            return exe
    return None


def _extract_with_bsdtar(path: Path, dest: Path) -> None:
    exe = find_bsdtar()
    if not exe:
        raise ArchiveRefused(
            "Unpacking .rar needs 'unrar' or 'bsdtar', neither is installed.")
    try:
        # bsdtar refuses absolute and ".." member paths by default (no -P).
        proc = subprocess.run([exe, "-xf", str(path), "-C", str(dest)],
                              capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        raise ArchiveRefused(f"bsdtar error: {exc}") from exc
    if proc.returncode != 0:
        raise ArchiveRefused(f"bsdtar error: {proc.stderr.strip()[:200]}")


def _extract(path: Path, dest: Path, quota: _Quota) -> list[str]:
    """Unpack `path` into `dest`; returns the refused (unsafe) member names."""
    ext = path.suffix.lower()
    if ext == ".zip":
        return _extract_zip(path, dest, quota)
    if ext in (".tar", ".tgz", ".gz"):
        try:
            return _extract_tar(path, dest, quota)
        except tarfile.ReadError:
            if ext != ".gz":
                raise
            _extract_gzip(path, dest, quota)
            return []
    if ext == ".7z":
        return _extract_7z(path, dest, quota)
    if ext == ".rar":
        return _extract_rar(path, dest, quota)
    raise ArchiveRefused(f"Unsupported archive type: {ext}")


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "password" in text.lower() or "encrypt" in text.lower() \
            or type(exc).__name__ == "PasswordRequired":
        return PASSWORD_MESSAGE
    return f"Could not unpack the archive: {text[:200]}"


# ------------------------------------------------------------- conversion
def convert(path: Path, out_pdf: Path) -> ConversionResult:
    start = time.time()
    path = Path(path)

    def result(status: Status, message: str, engine: str = "archive",
               output: Path | None = None) -> ConversionResult:
        return ConversionResult(source=path, status=status, output=output,
                                message=message, engine=engine,
                                duration_s=time.time() - start)

    level = _LEVEL.get() or _Level(depth=0, budget=_Budget(MAX_TOTAL_BYTES))
    if level.depth >= MAX_DEPTH:
        return result(Status.SKIPPED, f"Nested deeper than {MAX_DEPTH} archive "
                                      f"levels - not expanded.")

    token = _LEVEL.set(_Level(level.depth + 1, level.budget))
    workdir = Path(tempfile.mkdtemp(prefix="cv_arc_"))
    extract_dir = workdir / "x"
    try:
        os.makedirs(long_path(extract_dir), exist_ok=True)
        quota = _Quota(os.path.getsize(long_path(path)), level.budget)
        try:
            refused = _extract(path, extract_dir, quota)
        except ArchiveRefused as exc:
            return result(Status.SKIPPED, str(exc))
        except Exception as exc:  # noqa: BLE001 - corrupt or exotic archive
            return result(Status.SKIPPED, _friendly_error(exc))

        parts, problems = _convert_members(extract_dir, workdir)
        problems += [f"{name}: unsafe path refused" for name in refused]
        if not parts:
            detail = f" ({'; '.join(problems[:3])})" if problems else ""
            return result(Status.SKIPPED,
                          f"Nothing convertible in the archive{detail}.")

        os.makedirs(long_path(out_pdf).parent, exist_ok=True)
        pages, unreadable = merge_pdfs(parts, out_pdf)
        if not pages:
            return result(Status.FAILED,
                          "None of the converted parts could be merged.")
        note = f"Archive: {len(parts) - len(unreadable)} file(s) merged"
        left_out = len(problems) + len(unreadable)
        if left_out:
            note += f", {left_out} left out (e.g. {(problems + unreadable)[0]})"
        return result(Status.SUCCESS, note + ".", engine="archive+merge",
                      output=out_pdf)
    except Exception as exc:  # noqa: BLE001
        return result(Status.FAILED, f"Archive processing error: {exc}")
    finally:
        _LEVEL.reset(token)
        shutil.rmtree(long_path(workdir), ignore_errors=True)


def _convert_members(extract_dir: Path,
                     workdir: Path) -> tuple[list[Path], list[str]]:
    """Convert every unpacked file; returns (part PDFs, problem notes)."""
    from . import convert_file  # late import (circular dependency)

    parts: list[Path] = []
    problems: list[str] = []
    files = [p for p, _size in walk_entries(extract_dir)]
    for i, inner in enumerate(files):
        rel = inner.relative_to(extract_dir).as_posix()
        if inner.suffix.lower() == ".pdf":
            parts.append(inner)
            continue
        part_pdf = workdir / f"part_{i:04d}.pdf"
        try:
            res = convert_file(long_path(inner), long_path(part_pdf))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{rel}: {exc}")
            continue
        if res.ok and os.path.exists(long_path(part_pdf)):
            parts.append(part_pdf)
        else:
            problems.append(f"{rel}: {res.message or res.status.value}")
    return parts, problems
