"""JavaScript `LanguageParser`.

Purpose:       Extract classes, functions, methods, parameters, and imports from
                JavaScript source using tree-sitter's `javascript` grammar.
Responsibility: Map JS-specific node types onto the shared `extract_symbols`
                walker; JS's grammar already has a dedicated `method_definition`
                node type distinct from `function_declaration`, so (unlike Python)
                no nesting-based reclassification is needed here — it falls out of
                `extract_symbols`'s generic rule as a no-op.
Depends on:    tree_sitter, tree_sitter_language_pack, domain/parsing/entities.py,
                domain/errors.py, infrastructure/parsing/treesitter_support.py,
                infrastructure/parsing/ecmascript_shared.py.
Depended on by: infrastructure/parsing/registry.py.

Arrow functions (`const f = (a, b) => ...`) are intentionally not extracted as
symbols — an arrow function has no `name` field of its own (its "name," if any,
comes from the variable it's assigned to, which is a different node entirely) and
including it would mean either inventing a name-inference heuristic or emitting
unnamed symbols, both out of the "extract at minimum" scope. Named function
declarations and class methods, which the brief's minimum list actually asks for,
are unaffected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from tree_sitter_language_pack import get_parser

from forge.domain.errors import ParseFailure
from forge.domain.parsing.entities import Language, Parameter, ParsedFile, SymbolKind
from forge.infrastructure.parsing.ecmascript_shared import (
    SYMBOL_NODE_TYPES,
    extract_ecmascript_imports,
    pattern_name,
)
from forge.infrastructure.parsing.treesitter_support import (
    deterministic_id,
    extract_symbols,
    text_of_or_none,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_PARAMETER_NODE_TYPES = frozenset(
    {"identifier", "assignment_pattern", "rest_pattern", "object_pattern", "array_pattern"}
)


class _JavaScriptSymbolSpec:
    def symbol_kind_for(self, node_type: str) -> SymbolKind | None:
        return SYMBOL_NODE_TYPES.get(node_type)

    def extract_parameters(self, node: Node) -> tuple[Parameter, ...]:
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return ()
        result: list[Parameter] = []
        for child in params_node.children:
            if child.type not in _PARAMETER_NODE_TYPES:
                continue
            parameter = _extract_parameter(child, len(result))
            if parameter is not None:
                result.append(parameter)
        return tuple(result)


def _extract_parameter(node: Node, position: int) -> Parameter | None:
    if node.type == "assignment_pattern":
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        name = pattern_name(left) if left is not None else None
        if name is None:
            return None
        return Parameter(
            name=name, position=position, annotation=None, default_value=text_of_or_none(right)
        )

    name = pattern_name(node)
    if name is None:
        return None
    return Parameter(name=name, position=position, annotation=None, default_value=None)


class JavaScriptParser:
    """`LanguageParser` for `.js`/`.jsx` source."""

    language = Language.JAVASCRIPT

    def __init__(self) -> None:
        self._parser = get_parser("javascript")
        self._spec = _JavaScriptSymbolSpec()

    def parse(self, *, repository_id: UUID, file_path: str, source: bytes) -> ParsedFile:
        try:
            tree = self._parser.parse(source)
        except Exception as exc:
            raise ParseFailure(f"tree-sitter failed to parse {file_path!r}: {exc}") from exc

        root = tree.root_node
        symbols = extract_symbols(
            root, repository_id=repository_id, file_path=file_path, spec=self._spec
        )
        imports = extract_ecmascript_imports(
            root, repository_id=repository_id, file_path=file_path
        )

        return ParsedFile(
            id=deterministic_id(str(repository_id), file_path),
            repository_id=repository_id,
            path=file_path,
            language=Language.JAVASCRIPT,
            symbols=symbols,
            imports=imports,
            has_syntax_errors=root.has_error,
        )
