"""Shared tree-sitter plumbing for language parsers.

Purpose:       Everything that's identical across `PythonParser`,
                `JavaScriptParser`, and `TypeScriptParser` — 0-based-point-to-
                `SourceLocation` conversion, deterministic id generation, source-
                text extraction, and the generic symbol-extraction walk — lives
                here exactly once. Each language parser supplies a small
                `SymbolExtractionSpec` (which node types are classes/functions,
                how to pull a name off a matched node) and everything else
                (recursion, class-nesting tracking, id/location construction) is
                shared.
Responsibility: Language-agnostic tree-sitter mechanics. No language-specific node
                type names appear in this file.
Depends on:    tree_sitter, domain/parsing/entities.py.
Depended on by: infrastructure/parsing/{python,javascript,typescript}_parser.py.

Why a shared walker instead of three independent implementations: probing all
three grammars (python/javascript/typescript, via `tree_sitter_language_pack`)
during planning showed the *field names* a definition node exposes (`name`,
`parameters`, `body`) are consistent across all three even though the *node type*
names differ (Python's `function_definition` covers both functions and methods;
JS/TS have a dedicated `method_definition`). One generic rule — "a function-kind
node found while inside a class body is a METHOD, otherwise a FUNCTION" — handles
that difference uniformly, which is what `extract_symbols` below implements once.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from forge.domain.parsing.entities import (
    CallReference,
    Parameter,
    SourceLocation,
    Symbol,
    SymbolKind,
)

if TYPE_CHECKING:
    from tree_sitter import Node

# Fixed, arbitrary namespace for every id this module mints — what makes
# `deterministic_id` actually deterministic across processes/runs, not just
# within one. Generated once with `uuid.uuid4()`; never changes.
_ID_NAMESPACE = uuid.UUID("6f6b6bd0-6b8e-4e7a-9e3b-9a6f7f6e0b3f")

# Separator unlikely to appear inside any component (a path, a qualified name) —
# join+separator is only there to prevent ("a","bc") and ("ab","c") from
# colliding, not for readability.
_ID_SEPARATOR = "\x1f"


def deterministic_id(*parts: str) -> UUID:
    """A stable `uuid5` derived from `parts` — the same inputs always produce the
    same id, which is what lets re-parsing an unchanged file leave existing
    `Symbol`/`ParsedFile`/`Import` ids unchanged (see docs/architecture/
    03-parser-engine.md, "Stable identifiers")."""
    return uuid.uuid5(_ID_NAMESPACE, _ID_SEPARATOR.join(parts))


def location_of(node: Node) -> SourceLocation:
    """Convert a tree-sitter node's 0-based `Point`s into a 1-based
    `SourceLocation` — tree-sitter reports rows/columns from 0; every other part
    of Forge (and every editor a user might cross-reference against) counts lines
    from 1."""
    start_row, start_col = node.start_point
    end_row, end_col = node.end_point
    return SourceLocation(
        start_line=start_row + 1,
        end_line=end_row + 1,
        start_column=start_col,
        end_column=end_col,
    )


def text_of(node: Node) -> str:
    """The exact source text a node spans, decoded permissively — used for names,
    type annotations, and default-value expressions, none of which Forge
    interprets, only stores verbatim."""
    raw = node.text
    return raw.decode("utf-8", errors="replace") if raw is not None else ""


def text_of_or_none(node: Node | None) -> str | None:
    """`text_of`, but `None` in is `None` out — for optional fields (a default
    value, a type annotation) where "absent" and "empty text" both mean the same
    thing to Forge: no value to record."""
    if node is None:
        return None
    text = text_of(node)
    return text or None


class SymbolExtractionSpec(Protocol):
    """The language-specific hooks `extract_symbols` needs. Each `LanguageParser`
    implements this once for its grammar; `extract_symbols` owns the recursion,
    class-nesting tracking, and id/location construction."""

    def symbol_kind_for(self, node_type: str) -> SymbolKind | None:
        """Return the `SymbolKind` a node of this tree-sitter `node_type`
        represents, or `None` if this node type isn't a class/function/method
        definition at all."""
        ...

    def extract_parameters(self, node: Node) -> tuple[Parameter, ...]:
        """Parameters for a matched function/method-kind node. Called only for
        nodes whose `symbol_kind_for` result is `FUNCTION` or `METHOD`."""
        ...

    def extract_base_classes(self, node: Node) -> tuple[str, ...]:
        """Base-class expression text for a matched class-kind node (Phase 4 —
        see domain/parsing/entities.py::Symbol.base_class_names). Called only
        for nodes whose effective kind is `CLASS`."""
        ...

    def extract_calls(self, node: Node) -> tuple[CallReference, ...]:
        """Call sites found directly in a matched function/method-kind node's
        body — excluding any nested function/class definition's own body,
        which gets its own `Symbol` and its own `extract_calls` call when the
        walk reaches it (Phase 4 — see domain/parsing/entities.py::Symbol.calls).
        Called only for nodes whose effective kind is `FUNCTION` or `METHOD`."""
        ...


def extract_symbols(
    root: Node,
    *,
    repository_id: UUID,
    file_path: str,
    spec: SymbolExtractionSpec,
    name_field: str = "name",
) -> tuple[Symbol, ...]:
    """Walk `root`, producing one `Symbol` per class/function/method-kind node.

    Every nested symbol is qualified by its enclosing symbol. This keeps
    deterministic IDs unique for nested functions/classes while preserving
    the distinction between Python methods and nested functions.
    """

    symbols: list[Symbol] = []

    # (symbol_id, qualified_name, is_class)
    Enclosing = tuple[UUID, str, bool]

    def walk(node: Node, enclosing: Enclosing | None) -> None:
        kind = spec.symbol_kind_for(node.type)
        next_enclosing = enclosing

        if kind is not None:
            name_node = node.child_by_field_name(name_field)
            name = text_of(name_node) if name_node is not None else None

            if name:
                effective_kind = kind

                # A Python function directly inside a class is a METHOD.
                # A function nested inside a method/function is still a FUNCTION.
                if (
                    kind is SymbolKind.FUNCTION
                    and enclosing is not None
                    and enclosing[2]
                ):
                    effective_kind = SymbolKind.METHOD

                parent_id: UUID | None = None
                qualified_name = name

                if enclosing is not None:
                    parent_id, parent_qualified_name, _ = enclosing
                    qualified_name = f"{parent_qualified_name}.{name}"

                # Include source location in the deterministic ID so that
                # multiple same-named definitions in the same lexical scope
                # remain distinct.
                location = location_of(node)

                symbol_id = deterministic_id(
                    str(repository_id),
                    file_path,
                    qualified_name,
                    effective_kind.value,
                    str(location.start_line),
                    str(location.start_column),
                )

                is_class = effective_kind is SymbolKind.CLASS
                parameters = (
                    () if is_class else spec.extract_parameters(node)
                )
                base_class_names = (
                    spec.extract_base_classes(node) if is_class else ()
                )
                calls = () if is_class else spec.extract_calls(node)

                symbols.append(
                    Symbol(
                        id=symbol_id,
                        kind=effective_kind,
                        name=name,
                        qualified_name=qualified_name,
                        location=location,
                        parameters=parameters,
                        parent_symbol_id=parent_id,
                        base_class_names=base_class_names,
                        calls=calls,
                    )
                )

                # Track EVERY symbol, not just classes.
                # The bool tells us whether a directly nested Python function
                # should be classified as a METHOD.
                next_enclosing = (symbol_id, qualified_name, is_class)

        for child in node.children:
            walk(child, next_enclosing)

    walk(root, None)
    return tuple(symbols)

def find_within_excluding(
    node: Node, target_types: frozenset[str], boundary_types: frozenset[str]
) -> list[Node]:
    """Every descendant of `node` (`node` itself excluded) whose type is in
    `target_types`, never descending into a subtree rooted at a `boundary_types`
    node. Used by `extract_calls` implementations to collect a function's own
    call sites without also collecting calls that belong to a nested function/
    class definition — that nested definition gets its own `Symbol` and its own
    `extract_calls` call when the walk in `extract_symbols` reaches it
    separately; without the boundary, a call inside a closure would be counted
    against both the inner and outer symbol.
    """
    found: list[Node] = []

    def walk(n: Node) -> None:
        for child in n.children:
            if child.type in boundary_types:
                continue
            if child.type in target_types:
                found.append(child)
            walk(child)

    walk(node)
    return found


def find_all(root: Node, node_types: frozenset[str]) -> list[Node]:
    """Every descendant of `root` (root itself excluded) whose `.type` is in
    `node_types`, in source order — used for imports, where there's no nesting
    context to track (unlike symbols, an import is never "inside" another
    import), so the full generic-walk machinery `extract_symbols` needs isn't
    warranted."""
    found: list[Node] = []

    def walk(node: Node) -> None:
        for child in node.children:
            if child.type in node_types:
                found.append(child)
            walk(child)

    walk(root)
    return found
