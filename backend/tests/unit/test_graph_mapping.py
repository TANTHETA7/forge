"""Unit tests for `infrastructure/graph/graph_mapping.py` — pure computation,
zero I/O, mirroring how Phase 4's resolvers are tested against real data with
no persistence involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.graph.entities import GraphNodeKind, GraphRelationshipKind
from forge.domain.parsing.entities import Language, ParsedFile, SourceLocation, Symbol, SymbolKind
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from forge.infrastructure.graph.graph_mapping import map_repository_graph

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _repository() -> Repository:
    now = datetime.now(UTC)
    return Repository(
        id=uuid4(),
        project_id=uuid4(),
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="Demo",
        workspace_path="/tmp/does-not-matter",
        status=RepositoryStatus.READY,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _file(path: str, symbols: tuple[Symbol, ...] = ()) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=uuid4(),
        path=path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=(),
        has_syntax_errors=False,
    )


def _symbol(
    name: str, kind: SymbolKind = SymbolKind.FUNCTION, parent_symbol_id=None
) -> Symbol:
    return Symbol(
        id=uuid4(),
        kind=kind,
        name=name,
        qualified_name=name,
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=parent_symbol_id,
    )


def _import_edge(
    repository_id, source_file_id, target_file_id, status=ResolutionStatus.RESOLVED
) -> DependencyEdge:
    return DependencyEdge(
        id=uuid4(),
        repository_id=repository_id,
        kind=DependencyKind.IMPORTS,
        resolution_status=status,
        source_file_id=source_file_id,
        source_symbol_id=None,
        target_file_id=target_file_id if status is ResolutionStatus.RESOLVED else None,
        target_symbol_id=None,
        raw_target_expression=".utils",
        location=_LOCATION,
        detail=None,
    )


def _symbol_edge(
    repository_id,
    kind,
    source_file_id,
    source_symbol_id,
    target_symbol_id,
    status=ResolutionStatus.RESOLVED,
) -> DependencyEdge:
    return DependencyEdge(
        id=uuid4(),
        repository_id=repository_id,
        kind=kind,
        resolution_status=status,
        source_file_id=source_file_id,
        source_symbol_id=source_symbol_id,
        target_file_id=None,
        target_symbol_id=target_symbol_id if status is ResolutionStatus.RESOLVED else None,
        raw_target_expression="callee",
        location=_LOCATION,
        detail=None,
    )


def test_maps_repository_file_and_symbol_nodes() -> None:
    repository = _repository()
    symbol = _symbol("helper")
    file = _file("main.py", symbols=(symbol,))

    nodes, relationships = map_repository_graph(repository, [file], [])

    kinds = {node.kind for node in nodes}
    assert kinds == {GraphNodeKind.REPOSITORY, GraphNodeKind.FILE, GraphNodeKind.SYMBOL}
    assert len(nodes) == 3  # one repository, one file, one symbol

    node_ids = {node.id for node in nodes}
    assert repository.id in node_ids
    assert file.id in node_ids
    assert symbol.id in node_ids


def test_maps_contains_and_defines_relationships() -> None:
    repository = _repository()
    symbol = _symbol("helper")
    file = _file("main.py", symbols=(symbol,))

    _, relationships = map_repository_graph(repository, [file], [])

    contains = [r for r in relationships if r.kind is GraphRelationshipKind.CONTAINS]
    defines = [r for r in relationships if r.kind is GraphRelationshipKind.DEFINES]
    assert len(contains) == 1
    assert contains[0].source_id == repository.id
    assert contains[0].target_id == file.id
    assert contains[0].dependency_edge_id is None
    assert len(defines) == 1
    assert defines[0].source_id == file.id
    assert defines[0].target_id == symbol.id


def test_symbol_node_carries_kind_as_a_property_not_a_separate_label() -> None:
    repository = _repository()
    function_symbol = _symbol("helper", kind=SymbolKind.FUNCTION)
    class_symbol = _symbol("Widget", kind=SymbolKind.CLASS)
    file = _file("main.py", symbols=(function_symbol, class_symbol))

    nodes, _ = map_repository_graph(repository, [file], [])

    symbol_nodes = [n for n in nodes if n.kind is GraphNodeKind.SYMBOL]
    assert len(symbol_nodes) == 2
    assert all(n.kind is GraphNodeKind.SYMBOL for n in symbol_nodes)  # one label for both
    properties_by_name = {n.properties["name"]: n.properties for n in symbol_nodes}
    assert properties_by_name["helper"]["kind"] == "function"
    assert properties_by_name["Widget"]["kind"] == "class"


def test_resolved_import_edge_becomes_a_file_imports_file_relationship() -> None:
    repository = _repository()
    source_file = _file("main.py")
    target_file = _file("utils.py")
    edge = _import_edge(repository.id, source_file.id, target_file.id)

    _, relationships = map_repository_graph(repository, [source_file, target_file], [edge])

    imports = [r for r in relationships if r.kind is GraphRelationshipKind.IMPORTS]
    assert len(imports) == 1
    assert imports[0].source_id == source_file.id
    assert imports[0].target_id == target_file.id
    assert imports[0].dependency_edge_id == edge.id
    assert imports[0].properties["raw_target_expression"] == ".utils"


def test_unresolved_import_edge_produces_no_relationship() -> None:
    repository = _repository()
    source_file = _file("main.py")
    edge = _import_edge(repository.id, source_file.id, None, status=ResolutionStatus.UNRESOLVED)

    _, relationships = map_repository_graph(repository, [source_file], [edge])

    assert [r for r in relationships if r.kind is GraphRelationshipKind.IMPORTS] == []


def test_ambiguous_import_edge_produces_no_relationship() -> None:
    repository = _repository()
    source_file = _file("main.py")
    target_file = _file("utils.py")
    edge = _import_edge(
        repository.id, source_file.id, target_file.id, status=ResolutionStatus.AMBIGUOUS
    )
    # Even an AMBIGUOUS edge that happens to carry a target_file_id (the
    # "first/preferred candidate" case documented on ModuleResolution) must
    # not become a relationship — only RESOLVED does.
    object.__setattr__(edge, "target_file_id", target_file.id)

    _, relationships = map_repository_graph(repository, [source_file, target_file], [edge])

    assert [r for r in relationships if r.kind is GraphRelationshipKind.IMPORTS] == []


def test_empty_edges_still_projects_structural_nodes_and_relationships() -> None:
    repository = _repository()
    file = _file("main.py", symbols=(_symbol("helper"),))

    nodes, relationships = map_repository_graph(repository, [file], [])

    assert len(nodes) == 3
    assert {r.kind for r in relationships} == {
        GraphRelationshipKind.CONTAINS,
        GraphRelationshipKind.DEFINES,
    }


def test_every_node_and_relationship_carries_repository_id() -> None:
    repository = _repository()
    file = _file("main.py", symbols=(_symbol("helper"),))
    edge = _import_edge(repository.id, file.id, file.id)

    nodes, relationships = map_repository_graph(repository, [file], [edge])

    assert all(node.repository_id == repository.id for node in nodes)
    assert all(rel.repository_id == repository.id for rel in relationships)


def test_method_gets_a_contains_relationship_from_its_class() -> None:
    repository = _repository()
    class_symbol = _symbol("Dog", kind=SymbolKind.CLASS)
    method_symbol = _symbol(
        "bark", kind=SymbolKind.METHOD, parent_symbol_id=class_symbol.id
    )
    file = _file("dog.py", symbols=(class_symbol, method_symbol))

    _, relationships = map_repository_graph(repository, [file], [])

    contains = [r for r in relationships if r.kind is GraphRelationshipKind.CONTAINS]
    class_to_method = [r for r in contains if r.source_id == class_symbol.id]
    assert len(class_to_method) == 1
    assert class_to_method[0].target_id == method_symbol.id
    assert class_to_method[0].dependency_edge_id is None


def test_resolved_calls_edge_becomes_symbol_calls_symbol_relationship() -> None:
    repository = _repository()
    caller = _symbol("main")
    callee = _symbol("helper")
    file = _file("main.py", symbols=(caller, callee))
    edge = _symbol_edge(
        repository.id, DependencyKind.CALLS, file.id, caller.id, callee.id
    )

    _, relationships = map_repository_graph(repository, [file], [edge])

    calls = [r for r in relationships if r.kind is GraphRelationshipKind.CALLS]
    assert len(calls) == 1
    assert calls[0].source_id == caller.id
    assert calls[0].target_id == callee.id
    assert calls[0].dependency_edge_id == edge.id


def test_resolved_inherits_edge_becomes_symbol_inherits_symbol_relationship() -> None:
    repository = _repository()
    base = _symbol("Animal", kind=SymbolKind.CLASS)
    sub = _symbol("Dog", kind=SymbolKind.CLASS)
    file = _file("dog.py", symbols=(base, sub))
    edge = _symbol_edge(repository.id, DependencyKind.INHERITS, file.id, sub.id, base.id)

    _, relationships = map_repository_graph(repository, [file], [edge])

    inherits = [r for r in relationships if r.kind is GraphRelationshipKind.INHERITS]
    assert len(inherits) == 1
    assert inherits[0].source_id == sub.id
    assert inherits[0].target_id == base.id


def test_unresolved_calls_edge_produces_no_relationship() -> None:
    repository = _repository()
    caller = _symbol("main")
    file = _file("main.py", symbols=(caller,))
    edge = _symbol_edge(
        repository.id,
        DependencyKind.CALLS,
        file.id,
        caller.id,
        None,
        status=ResolutionStatus.UNRESOLVED,
    )

    _, relationships = map_repository_graph(repository, [file], [edge])

    assert [r for r in relationships if r.kind is GraphRelationshipKind.CALLS] == []


def test_no_references_relationship_kind_is_ever_produced() -> None:
    # DependencyKind.REFERENCES is declared for forward extensibility, but no
    # Phase 4 resolver produces it — confirm the mapper has nothing wired for
    # it either (see module docstring).
    assert not hasattr(GraphRelationshipKind, "REFERENCES")
