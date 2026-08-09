"""Tests for FilesystemFileDiscovery — pure filesystem I/O, tmp_path only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forge.domain.parsing.entities import DiscoveredFile, SkippedFile
from forge.infrastructure.parsing.file_discovery import FilesystemFileDiscovery


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _discover(
    workspace: Path, *, max_file_bytes: int = 1024 * 1024
) -> list[DiscoveredFile | SkippedFile]:
    return list(FilesystemFileDiscovery(max_file_bytes=max_file_bytes).discover(workspace))


def test_discovers_files_in_nested_directories(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", b"pass")
    _write(tmp_path / "src" / "b.py", b"pass")
    _write(tmp_path / "src" / "lib" / "c.py", b"pass")

    results = _discover(tmp_path)
    discovered = {r.relative_path for r in results if isinstance(r, DiscoveredFile)}

    assert discovered == {"a.py", "src/b.py", "src/lib/c.py"}


def test_discovered_file_content_matches_source(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", b"print('hi')")
    results = _discover(tmp_path)
    assert results[0].content == b"print('hi')"


def test_skips_ignored_vendor_directories(tmp_path: Path) -> None:
    _write(tmp_path / "node_modules" / "pkg" / "index.js", b"module.exports={}")
    _write(tmp_path / ".git" / "HEAD", b"ref: refs/heads/main")
    _write(tmp_path / "src" / "app.py", b"pass")

    results = _discover(tmp_path)
    discovered = {r.relative_path for r in results if isinstance(r, DiscoveredFile)}

    assert discovered == {"src/app.py"}


def test_binary_file_is_skipped_not_errored(tmp_path: Path) -> None:
    _write(tmp_path / "image.dat", b"\x89PNG\x00\x01\x02")
    results = _discover(tmp_path)

    assert len(results) == 1
    assert isinstance(results[0], SkippedFile)
    assert results[0].stage is None
    assert "binary" in results[0].reason


def test_oversized_file_is_skipped_not_errored(tmp_path: Path) -> None:
    _write(tmp_path / "big.py", b"x" * 100)
    results = _discover(tmp_path, max_file_bytes=10)

    assert len(results) == 1
    assert isinstance(results[0], SkippedFile)
    assert results[0].stage is None
    assert "exceeding" in results[0].reason


def test_empty_workspace_discovers_nothing(tmp_path: Path) -> None:
    assert _discover(tmp_path) == []


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation requires elevated privileges on Windows"
)
def test_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_secret.py"
    _write(outside, b"SECRET = 1")
    (tmp_path / "link.py").symlink_to(outside)
    _write(tmp_path / "real.py", b"pass")

    results = _discover(tmp_path)
    discovered = {r.relative_path for r in results if isinstance(r, DiscoveredFile)}

    assert discovered == {"real.py"}
    outside.unlink(missing_ok=True)
