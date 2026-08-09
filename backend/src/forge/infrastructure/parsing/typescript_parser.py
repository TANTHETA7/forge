"""TypeScript `LanguageParser`.

Purpose:       Extract classes, functions, methods, parameters, and imports from
                TypeScript (`.ts`) and TSX (`.tsx`) source.
Responsibility: Same symbol/import shape as JavaScript (shared via
                ecmascript_shared.py — TS's grammar is a superset of JS's for
                these constructs) plus TS-specific parameter unwrapping:
                `required_parameter`/`optional_parameter` wrap a `pattern` field
                (an `identifier` or `rest_pattern`, same as JS's bare parameters)
                and an optional `type`/`value` field for the annotation/default,
                where JS uses the plain pattern nodes directly.
Depends on:    tree_sitter, tree_sitter_language_pack, domain/parsing/entities.py,
                domain/errors.py, infrastructure/parsing/treesitter_support.py,
                infrastructure/parsing/ecmascript_shared.py.
Depended on by: infrastructure/parsing/registry.py.

`.tsx` files route to the `tsx` grammar (a distinct grammar in
`tree_sitter_language_pack`, not just `typescript` with a flag) — both are
selected via the same `Language.TYPESCRIPT` value; `registry.py` decides which
grammar variant based on the file extension, not on a second `Language` member,
since both extensions represent the same language to every consumer above the
parser.
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
    strip_type_annotation,
)
from forge.infrastructure.parsing.treesitter_support import (
    deterministic_id,
    extract_symbols,
    text_of_or_none,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_WRAPPED_PARAMETER_NODE_TYPES = frozenset({"required_parameter", "optional_parameter"})
_PLAIN_PARAMETER_NODE_TYPES = frozenset(
    {"identifier", "assignment_pattern", "rest_pattern", "object_pattern", "array_pattern"}
)


class _TypeScriptSymbolSpec:
    def symbol_kind_for(self, node_type: str) -> SymbolKind | None:
        return SYMBOL_NODE_TYPES.get(node_type)

    def extract_parameters(self, node: Node) -> tuple[Parameter, ...]:
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return ()
        result: list[Parameter] = []
        for child in params_node.children:
            parameter: Parameter | None = None
            if child.type in _WRAPPED_PARAMETER_NODE_TYPES:
                parameter = _extract_wrapped_parameter(child, len(result))
            elif child.type in _PLAIN_PARAMETER_NODE_TYPES:
                parameter = _extract_plain_parameter(child, len(result))
            if parameter is not None:
                result.append(parameter)
        return tuple(result)


def _extract_wrapped_parameter(node: Node, position: int) -> Parameter | None:
    pattern_node = node.child_by_field_name("pattern")
    if pattern_node is None:
        return None
    name = pattern_name(pattern_node)
    if name is None:
        return None
    type_node = node.child_by_field_name("type")
    value_node = node.child_by_field_name("value")
    return Parameter(
        name=name,
        position=position,
        annotation=strip_type_annotation(type_node),
        default_value=text_of_or_none(value_node),
    )


def _extract_plain_parameter(node: Node, position: int) -> Parameter | None:
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


class TypeScriptParser:
    """`LanguageParser` for `.ts`/`.tsx` source."""

    language = Language.TYPESCRIPT

    def __init__(self, *, tsx: bool = False) -> None:
        self._parser = get_parser("tsx" if tsx else "typescript")
        self._spec = _TypeScriptSymbolSpec()

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
            language=Language.TYPESCRIPT,
            symbols=symbols,
            imports=imports,
            has_syntax_errors=root.has_error,
        )
