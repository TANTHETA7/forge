"""Parser registry — selects the right `LanguageParser` for a file.

Purpose:       The single place that maps "a file path" to "the parser instance
                that handles it" — every future language is added here and
                nowhere else (see docs/architecture/03-parser-engine.md,
                "Extension strategy").
Responsibility: Construction/selection only — no parsing logic.
Depends on:    domain/parsing/ports.py, infrastructure/parsing/language_detection.py.
Depended on by: application/parsing/service.py (via
                domain/parsing/ports.py::ParserRegistry — never constructed
                directly by application code, see core/app_factory.py-style
                wiring in api/parsing.py).
"""

from __future__ import annotations

from forge.domain.parsing.entities import Language
from forge.domain.parsing.ports import LanguageParser
from forge.infrastructure.parsing.language_detection import detect_language, is_tsx


class DefaultParserRegistry:
    """`ParserRegistry` built from one `LanguageParser` instance per `Language`,
    plus a distinct instance for `.tsx` — `.tsx` shares `Language.TYPESCRIPT`
    (see infrastructure/parsing/typescript_parser.py's docstring) but needs the
    `tsx` tree-sitter grammar instead of `typescript`, so selection needs the
    file path, not just the detected language.
    """

    def __init__(
        self,
        *,
        python: LanguageParser,
        javascript: LanguageParser,
        typescript: LanguageParser,
        tsx: LanguageParser,
    ) -> None:
        self._by_language: dict[Language, LanguageParser] = {
            Language.PYTHON: python,
            Language.JAVASCRIPT: javascript,
            Language.TYPESCRIPT: typescript,
        }
        self._tsx = tsx

    def parser_for(self, file_path: str) -> LanguageParser | None:
        language = detect_language(file_path)
        if language is None:
            return None
        if language is Language.TYPESCRIPT and is_tsx(file_path):
            return self._tsx
        return self._by_language.get(language)
