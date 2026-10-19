"""Safety rules: untrusted archives, folder pairs that could destroy data, links."""

from __future__ import annotations

import io
import os
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest

from conftest import make_txt, make_zip, pdf_text

from cornverter.converters import Options, archive
from cornverter.converters.base import Status
from cornverter.scanner import Task, scan, scan_in_place, validate_paths
from cornverter.engine import execute_task


def _tar(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return path


def _nested_zip(path: Path, layers: int) -> Path:
    blob, name = b"deep text\n", "deep.txt"
    for i in range(layers):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name, blob)
        blob, name = buf.getvalue(), f"layer{layers - i}.zip"
    path.write_bytes(blob)
    return path


# ------------------------------------------------------------------ archives
def test_tar_members_escaping_the_folder_are_refused(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))
    absolute = (tmp_path / "abs_escape.txt").as_posix()
    src = _tar(tmp_path / "evil.tar", {
        "ok.txt": b"inside text\n",
        "../../../dotdot_escape.txt": b"x",
        absolute: b"x",
    })

    result = archive.convert(src, tmp_path / "evil.pdf")

    assert result.status is Status.SUCCESS, result.message
    assert "inside text" in pdf_text(tmp_path / "evil.pdf")
    assert "unsafe path refused" in result.message
    assert not (tmp_path / "dotdot_escape.txt").exists()
    assert not (tmp_path / "abs_escape.txt").exists()


def test_zip_bomb_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    written: list = []
    monkeypatch.setattr(archive, "_write_member", lambda *a: written.append(a))
    src = tmp_path / "bomb.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zeros.bin", b"\0" * (30 << 20))

    result = archive.convert(src, tmp_path / "bomb.pdf")

    assert result.status is Status.SKIPPED
    assert "zip bomb" in result.message
    assert written == []


def test_nested_archives_stop_at_the_depth_limit(tmp_path):
    ok = archive.convert(_nested_zip(tmp_path / "three.zip", 3),
                         tmp_path / "three.pdf")
    assert ok.status is Status.SUCCESS, ok.message
    assert "deep text" in pdf_text(tmp_path / "three.pdf")

    deep = archive.convert(_nested_zip(tmp_path / "four.zip", 4),
                           tmp_path / "four.pdf")
    assert deep.status is not Status.SUCCESS
    assert f"deeper than {archive.MAX_DEPTH}" in deep.message


def test_deep_member_path_is_extracted(tmp_path):
    name = "/".join(["d" * 38] * 6) + "/deep.txt"
    assert len(name) > 240
    src = make_zip(tmp_path / "deep.zip", {name: b"long path content\n"})

    result = archive.convert(src, tmp_path / "deep.pdf")

    assert result.status is Status.SUCCESS, result.message
    assert "long path content" in pdf_text(tmp_path / "deep.pdf")


def test_password_protected_zip_is_skipped_with_a_plain_message(tmp_path):
    src = make_zip(tmp_path / "secret.zip", {"secret.txt": b"x"})
    data = bytearray(src.read_bytes())
    data[6] |= 0x1                                     # local header flags
    central = data.find(b"PK\x01\x02")
    data[central + 8] |= 0x1                           # central directory flags
    src.write_bytes(bytes(data))

    result = archive.convert(src, tmp_path / "secret.pdf")

    assert result.status is Status.SKIPPED
    assert result.message == archive.PASSWORD_MESSAGE


# ------------------------------------------------------------- folder pairs
def test_folder_pairs_that_could_overwrite_or_scramble_are_refused(tmp_path):
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)

    assert "itself" in validate_paths(src, src, in_place=False)
    assert "parent" in validate_paths(src, tmp_path, in_place=False)
    assert "itself" in validate_paths(src, src, in_place=True)
    assert "parent" in validate_paths(src / "sub", src, in_place=True)
    assert validate_paths(src, tmp_path / "out", in_place=False) is None
    # A folder inside the input is fine: the scan never enters it.
    assert validate_paths(src, src / "pdf", in_place=False) is None


def test_existing_pdf_in_the_output_is_never_overwritten(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "report.txt")
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "report.pdf"
    existing.write_bytes(b"%PDF-1.4 unrelated")

    summary = scan(src, out, Options())
    assert summary.tasks == [] and summary.skipped_existing == 1

    # The worker checks again at execution time.
    task = Task(source=src / "report.txt", output=existing,
                category="text", size=1)
    assert execute_task(task, Options()).status is Status.SKIPPED
    assert existing.read_bytes() == b"%PDF-1.4 unrelated"

    assert len(scan(src, out, Options(overwrite=True)).tasks) == 1


# -------------------------------------------------------------------- links
@pytest.mark.skipif(os.name != "nt", reason="NTFS junctions")
def test_junctions_are_not_followed(tmp_path):
    import _winapi

    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "own.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    make_txt(outside / "foreign.txt")
    links = [src / "link_out", src / "loop"]
    _winapi.CreateJunction(str(outside), str(links[0]))
    _winapi.CreateJunction(str(src), str(links[1]))
    try:
        summary = scan_in_place(src, tmp_path / "backup", Options())
        assert [t.source.name for t in summary.tasks] == ["own.txt"]
        assert sorted(p.name for p in summary.skipped_links) == \
            ["link_out", "loop"]
        for task in summary.tasks:
            execute_task(task, Options())
        assert (outside / "foreign.txt").exists()
        assert list(outside.iterdir()) == [outside / "foreign.txt"]
    finally:
        for link in links:
            os.rmdir(link)
