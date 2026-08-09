"""Repository metadata scanner.

Purpose:       Produce a lightweight structural summary of an imported repository —
                file/directory counts, size, language mix, README/git presence —
                without parsing any file's contents. Content parsing is the future
                Parsing Engine's job (docs/architecture/02-engineering-specification.md
                §11); this module never opens a file for anything but `stat()`.
Responsibility: A single read-only filesystem walk over an already-materialized
                workspace.
Depends on:    pathlib (stdlib), domain/repository/entities.py,
                infrastructure/filesystem/workspace_walker.py.
Depended on by: application/repository_import/service.py, via
                domain/repository/ports.py::MetadataScanner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from forge.domain.repository.entities import RepositoryMetadata
from forge.infrastructure.filesystem.workspace_walker import walk_workspace

# Deliberately small and unambiguous — extended as real languages come up rather
# than guessed at wholesale (same "no placeholder code" discipline as the AST
# schema in the engineering spec).
_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
}


class FilesystemMetadataScanner:
    """A `MetadataScanner` that walks the workspace directory tree once."""

    def scan(self, workspace: Path) -> RepositoryMetadata:
        file_count = 0
        directory_count = 0
        total_size_bytes = 0
        language_file_counts: dict[str, int] = {}
        has_readme = False
        has_git = (workspace / ".git").exists()

        for entry in walk_workspace(workspace):
            if entry.is_dir():
                directory_count += 1
                continue

            file_count += 1
            try:
                total_size_bytes += entry.stat().st_size
            except OSError:
                pass

            if entry.name.upper().startswith("README"):
                has_readme = True

            language = _EXTENSION_LANGUAGE_MAP.get(entry.suffix.lower())
            if language:
                language_file_counts[language] = language_file_counts.get(language, 0) + 1

        return RepositoryMetadata(
            file_count=file_count,
            directory_count=directory_count,
            total_size_bytes=total_size_bytes,
            language_stats=_to_percentages(language_file_counts, file_count),
            has_readme=has_readme,
            has_git=has_git,
            scanned_at=datetime.now(UTC),
        )


def _to_percentages(counts: dict[str, int], total_files: int) -> dict[str, float]:
    if total_files == 0:
        return {}
    return {
        language: round((count / total_files) * 100, 1)
        for language, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    }
