"""Shared plumbing between JavaScript and TypeScript — both grammars agree on
symbol node types and import-statement shape (TS's grammar is a superset of JS's
for these constructs, confirmed by probing both during planning), so this is
where that overlap lives rather than duplicating it in
javascript_parser.py/typescript_parser.py. Parameter *wrapper* shapes differ
(plain `identifier`/`assignment_pattern`/`rest_pattern` in JS vs.
`required_parameter`/`optional_parameter` wrapping a `pattern` field in TS) —
`pattern_name` below is the piece that IS shared between them (extracting a bound
name off a pattern node), used directly by JS and by TS's unwrapping logic.

Depends on:    tree_sitter, domain/parsing/entities.py,
                infrastructure/parsing/treesitter_support.py.
Depended on by: infrastructure/parsing/{javascript,typescript}_parser.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from forge.domain.parsing.entities import CallReference, Import, SymbolKind
from forge.infrastructure.parsing.treesitter_support import (
    deterministic_id,
    find_all,
    find_within_excluding,
    location_of,
    text_of,
)

if TYPE_CHECKING:
    from tree_sitter import Node

SYMBOL_NODE_TYPES: dict[str, SymbolKind] = {
    "function_declaration": SymbolKind.FUNCTION,
    "class_declaration": SymbolKind.CLASS,
    "method_definition": SymbolKind.METHOD,
}

_IMPORT_NODE_TYPES = frozenset({"import_statement"})
_CALL_NODE_TYPES = frozenset({"call_expression"})

# A call site belongs to the nearest enclosing FUNCTION/METHOD/CLASS symbol —
# don't descend into a nested one's body when collecting the outer symbol's own
# calls (see treesitter_support.py::find_within_excluding). Same rationale as
# python_parser.py's equivalent constant.
_NESTED_DEFINITION_TYPES = frozenset(
    {"function_declaration", "class_declaration", "method_definition"}
)


def pattern_name(node: Node) -> str | None:
    """The bound name a parameter pattern introduces.

    `identifier` -> itself. `rest_pattern` (`...name`) -> the inner name, marker
    excluded (matching Parameter.name's documented contract). `object_pattern`/
    `array_pattern` (destructuring, e.g. `{a, b}`) -> the pattern's own source
    text verbatim, as a single synthetic name — Phase 3 doesn't expand a
    destructured parameter into one `Parameter` per bound name (out of the
    "extract at minimum" scope); the raw pattern is still visible rather than
    silently dropped.
    """
    if node.type == "identifier":
        return text_of(node)
    if node.type == "rest_pattern":
        inner = next((c for c in node.children if c.type == "identifier"), None)
        return text_of(inner) if inner is not None else None
    if node.type in ("object_pattern", "array_pattern"):
        return text_of(node)
    return None


def extract_class_heritage(node: Node) -> tuple[str, ...]:
    """Base-class expression text for a `class_declaration` node — JS and TS
    structure this differently (probed during planning, not assumed): JS's
    `class_heritage` child directly contains `extends` + the base expression;
    TS's `class_heritage` wraps an `extends_clause` (and optionally an
    `implements_clause`, deliberately ignored — `implements` is a type
    constraint, not inheritance) which itself contains `extends` + the base
    expression. Unwrapping `extends_clause` when present, then dropping the
    `extends` token, handles both shapes with one piece of logic. JS/TS only
    ever have a single base class (unlike Python's multiple inheritance), so
    this returns 0 or 1 items, never more.
    """
    heritage = next((c for c in node.children if c.type == "class_heritage"), None)
    if heritage is None:
        return ()
    extends_clause = next((c for c in heritage.children if c.type == "extends_clause"), None)
    container = extends_clause if extends_clause is not None else heritage
    return tuple(text_of(child) for child in container.children if child.type != "extends")


def extract_ecmascript_calls(node: Node) -> tuple[CallReference, ...]:
    """Call sites (`call_expression`) found directly in `node`'s body, excluding
    any nested function/class/method definition's own body — see
    treesitter_support.py::find_within_excluding."""
    calls = find_within_excluding(node, _CALL_NODE_TYPES, _NESTED_DEFINITION_TYPES)
    result = []
    for call in calls:
        function_node = call.child_by_field_name("function")
        if function_node is None:
            continue
        result.append(
            CallReference(callee_expression=text_of(function_node), location=location_of(call))
        )
    return tuple(result)


def strip_type_annotation(node: Node | None) -> str | None:
    """TS's `type_annotation` node's text includes the leading `: ` (e.g.
    `": number"`) — stripped here so `Parameter.annotation` matches Python's
    style (`"int"`, not `": int"`)."""
    if node is None:
        return None
    text = text_of(node)
    return text.removeprefix(":").strip() or None


def extract_ecmascript_imports(
    root: Node, *, repository_id: UUID, file_path: str
) -> tuple[Import, ...]:
    """`import X from "m"`, `import { a, b as c } from "m"`, `import * as ns from
    "m"`, `import "m"` (side-effect only) — one `Import` per `import_statement`,
    combining any default/namespace bound name into `alias` and every named
    import's original (pre-alias) name into `imported_names`, mirroring the
    from-import treatment in python_parser.py: Phase 4/5's `File --IMPORTS-->
    Module` edge cares which module was imported, not each local binding name.
    """
    imports: list[Import] = []
    for node in find_all(root, _IMPORT_NODE_TYPES):
        source_node = node.child_by_field_name("source")
        if source_node is None:
            continue
        module = text_of(source_node).strip("\"'")

        alias: str | None = None
        imported_names: list[str] = []

        clause = next((c for c in node.children if c.type == "import_clause"), None)
        if clause is not None:
            for child in clause.children:
                if child.type == "identifier":
                    alias = text_of(child)
                elif child.type == "namespace_import":
                    inner = next(
                        (c for c in child.children if c.type == "identifier"), None
                    )
                    if inner is not None:
                        alias = text_of(inner)
                elif child.type == "named_imports":
                    for specifier in child.children:
                        if specifier.type != "import_specifier":
                            continue
                        name_node = specifier.child_by_field_name("name")
                        if name_node is not None:
                            imported_names.append(text_of(name_node))

        location = location_of(node)
        imports.append(
            Import(
                id=deterministic_id(
                    str(repository_id), file_path, module, str(location.start_line)
                ),
                module=module,
                imported_names=tuple(imported_names),
                alias=alias,
                location=location,
            )
        )
    return tuple(imports)
