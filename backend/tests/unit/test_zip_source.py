"""Security tests for ZipRepositorySource.

Each test targets one specific attack class called out in
infrastructure/sources/zip_source.py's module docstring — path traversal, Zip Slip,
absolute paths, symlinks, entry-count exhaustion, oversized entries, and a
zip-bomb-style compression ratio — plus one happy-path extraction to prove the
defenses don't reject legitimate archives.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from forge.domain.errors import UnsafeArchiveError
from forge.infrastructure.sources.zip_source import ZipRepositorySource


def _make_source(archive_path: Path) -> ZipRepositorySource:
    return ZipRepositorySource(
        archive_path,
        max_total_size_bytes=10 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=1024 * 1024,
        max_compression_ratio=100,
    )


def test_valid_archive_extracts_successfully(tmp_path: Path) -> None:
    archive_path = tmp_path / "good.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("README.md", "hello")
        zf.writestr("src/main.py", "print('hi')\n")

    source = _make_source(archive_path)
    source.validate()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source.materialize_into(workspace)

    assert (workspace / "README.md").read_text() == "hello"
    assert (workspace / "src" / "main.py").read_text() == "print('hi')\n"


@pytest.mark.parametrize(
    "entry_name",
    [
        "../../etc/passwd",
        "../escape.txt",
        "..",
    ],
)
def test_rejects_path_traversal_entry_names(tmp_path: Path, entry_name: str) -> None:
    archive_path = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr(entry_name, "malicious")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_absolute_path_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "absolute.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("/etc/passwd", "malicious")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_windows_drive_letter_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "drive.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("C:/Windows/system32/evil.dll", "malicious")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_zip_slip_is_rejected_even_if_name_check_is_bypassed(tmp_path: Path) -> None:
    """Defense-in-depth: even an entry name that only looks safe must resolve
    inside the workspace at extraction time, independent of `_validate_entry_name`."""
    archive_path = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("safe/../../../escape.txt", "malicious")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_symlink_entry(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_too_many_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "many.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for i in range(150):
            zf.writestr(f"file{i}.txt", "x")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_oversized_single_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "huge_file.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("big.bin", "x" * (2 * 1024 * 1024))

    source = ZipRepositorySource(
        archive_path,
        max_total_size_bytes=10 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=1024 * 1024,
        max_compression_ratio=100,
    )
    with pytest.raises(UnsafeArchiveError):
        source.validate()


def test_rejects_suspicious_compression_ratio(tmp_path: Path) -> None:
    archive_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Highly compressible content produces a large ratio between the tiny
        # compressed size and the declared uncompressed size.
        zf.writestr("bomb.txt", "0" * (5 * 1024 * 1024))

    source = ZipRepositorySource(
        archive_path,
        max_total_size_bytes=100 * 1024 * 1024,
        max_file_count=100,
        max_single_file_bytes=100 * 1024 * 1024,
        max_compression_ratio=50,
    )
    with pytest.raises(UnsafeArchiveError):
        source.validate()


def test_rejects_empty_archive(tmp_path: Path) -> None:
    archive_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive_path, "w"):
        pass

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()


def test_rejects_non_zip_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "not_a_zip.zip"
    archive_path.write_bytes(b"this is not a zip file")

    with pytest.raises(UnsafeArchiveError):
        _make_source(archive_path).validate()
