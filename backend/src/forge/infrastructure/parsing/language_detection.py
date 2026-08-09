"""File-extension-based language detection for the parsing pipeline.

Purpose:       Map a file path to the `Language` the parser registry should route
                it to.
Responsibility: A small extension map scoped to exactly what Forge can parse in
                Phase 3 — deliberately separate from
                `infrastructure/scanner/metadata_scanner.py`'s extension map,
                which serves a different concern (repository-wide language
                percentage statistics across many more extensions than Forge
                parses, e.g. `.sql`, `.yaml`, `.md`). Conflating the two would
                couple the parsing pipeline's supported-language set to the
                repository-import module's display statistics, which happen to
                overlap today but have no reason to stay in lockstep.
Depends on:    domain/parsing/entities.py.
Depended on by: infrastructure/parsing/registry.py.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from forge.domain.parsing.entities import Language

_EXTENSION_LANGUAGE_MAP: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
}


def detect_language(file_path: str) -> Language | None:
    """The `Language` `file_path`'s extension maps to, or `None` if it isn't one
    Forge parses — `None` is a normal, expected result (an unsupported file),
    not an error."""
    suffix = PurePosixPath(file_path).suffix.lower()
    return _EXTENSION_LANGUAGE_MAP.get(suffix)


def is_tsx(file_path: str) -> bool:
    """Whether `file_path` needs the `tsx` grammar variant rather than plain
    `typescript` — both map to `Language.TYPESCRIPT` (see typescript_parser.py's
    docstring for why this isn't a separate `Language` member), so the registry
    needs this alongside `detect_language` to pick the right parser instance."""
    return PurePosixPath(file_path).suffix.lower() == ".tsx"
