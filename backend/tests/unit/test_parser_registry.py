"""Tests for language detection and the parser registry — pure, no I/O."""

from __future__ import annotations

from uuid import UUID

import pytest

from forge.domain.parsing.entities import Language, ParsedFile
from forge.infrastructure.parsing.language_detection import detect_language, is_tsx
from forge.infrastructure.parsing.registry import DefaultParserRegistry


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("main.py", Language.PYTHON),
        ("src/app.js", Language.JAVASCRIPT),
        ("src/App.jsx", Language.JAVASCRIPT),
        ("src/app.ts", Language.TYPESCRIPT),
        ("src/App.tsx", Language.TYPESCRIPT),
        ("README.md", None),
        ("styles.css", None),
        ("data.json", None),
        ("no_extension", None),
    ],
)
def test_detect_language(path: str, expected: Language | None) -> None:
    assert detect_language(path) == expected


def test_is_tsx() -> None:
    assert is_tsx("App.tsx") is True
    assert is_tsx("app.ts") is False
    assert is_tsx("app.py") is False


class _FakeParser:
    def __init__(self, language: Language, tag: str) -> None:
        self.language = language
        self.tag = tag

    def parse(self, *, repository_id: UUID, file_path: str, source: bytes) -> ParsedFile:
        raise NotImplementedError("not exercised by registry tests")


def _make_registry() -> DefaultParserRegistry:
    return DefaultParserRegistry(
        python=_FakeParser(Language.PYTHON, "python"),
        javascript=_FakeParser(Language.JAVASCRIPT, "javascript"),
        typescript=_FakeParser(Language.TYPESCRIPT, "typescript"),
        tsx=_FakeParser(Language.TYPESCRIPT, "tsx"),
    )


def test_registry_routes_python_files() -> None:
    parser = _make_registry().parser_for("main.py")
    assert isinstance(parser, _FakeParser)
    assert parser.tag == "python"


def test_registry_routes_ts_and_tsx_to_different_parser_instances() -> None:
    registry = _make_registry()
    ts_parser = registry.parser_for("app.ts")
    tsx_parser = registry.parser_for("App.tsx")

    assert isinstance(ts_parser, _FakeParser) and ts_parser.tag == "typescript"
    assert isinstance(tsx_parser, _FakeParser) and tsx_parser.tag == "tsx"


def test_registry_returns_none_for_unsupported_file() -> None:
    assert _make_registry().parser_for("README.md") is None
