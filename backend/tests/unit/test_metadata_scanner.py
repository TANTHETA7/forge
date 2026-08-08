"""Tests for FilesystemMetadataScanner."""

from __future__ import annotations

from pathlib import Path

from forge.infrastructure.scanner.metadata_scanner import FilesystemMetadataScanner


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_counts_files_and_directories(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Title")
    _write(tmp_path / "src" / "main.py", "print('hi')")
    _write(tmp_path / "src" / "utils.py", "x = 1")
    _write(tmp_path / "src" / "lib" / "helper.ts", "export const x = 1;")

    metadata = FilesystemMetadataScanner().scan(tmp_path)

    assert metadata.file_count == 4
    assert metadata.directory_count == 2  # src/, src/lib/
    assert metadata.total_size_bytes > 0


def test_detects_readme_case_insensitively(tmp_path: Path) -> None:
    _write(tmp_path / "readme.txt", "hi")
    metadata = FilesystemMetadataScanner().scan(tmp_path)
    assert metadata.has_readme is True


def test_no_readme_when_absent(tmp_path: Path) -> None:
    _write(tmp_path / "main.py", "pass")
    metadata = FilesystemMetadataScanner().scan(tmp_path)
    assert metadata.has_readme is False


def test_detects_git_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    metadata = FilesystemMetadataScanner().scan(tmp_path)
    assert metadata.has_git is True


def test_language_stats_are_percentages_of_recognized_files(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x")
    _write(tmp_path / "b.py", "x")
    _write(tmp_path / "c.py", "x")
    _write(tmp_path / "d.ts", "x")

    metadata = FilesystemMetadataScanner().scan(tmp_path)

    assert metadata.language_stats["Python"] == 75.0
    assert metadata.language_stats["TypeScript"] == 25.0


def test_ignores_git_and_dependency_directories(tmp_path: Path) -> None:
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "module.exports = {};")
    _write(tmp_path / "src" / "index.py", "pass")

    metadata = FilesystemMetadataScanner().scan(tmp_path)

    assert metadata.file_count == 1
    assert metadata.language_stats == {"Python": 100.0}


def test_empty_workspace_has_no_language_stats(tmp_path: Path) -> None:
    metadata = FilesystemMetadataScanner().scan(tmp_path)
    assert metadata.file_count == 0
    assert metadata.language_stats == {}
