"""Integration test for the code-intelligence HTTP surface.

Scope: full stack through the ASGI app — api -> application -> domain (fake
persistence for Postgres AND Neo4j) — proving the routers, schemas, DI
wiring, and query-param validation are correct end to end, mirroring
test_graph_api.py's established approach. Real-Neo4j semantic correctness
lives in test_neo4j_graph_intelligence.py and test_real_graph_intelligence.py
instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.graph_intelligence.dependencies import get_graph_intelligence_repository
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_project_repository,
    get_repository_repository,
)
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryGraphIntelligenceRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
)


@pytest.fixture
def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


@pytest.fixture
def intelligence(graph: InMemoryGraphRepository) -> InMemoryGraphIntelligenceRepository:
    return InMemoryGraphIntelligenceRepository(graph)


@pytest.fixture
def repositories() -> InMemoryRepositoryRepository:
    return InMemoryRepositoryRepository()


@pytest.fixture
def client(
    tmp_path: Path,
    graph: InMemoryGraphRepository,
    intelligence: InMemoryGraphIntelligenceRepository,
    repositories: InMemoryRepositoryRepository,
) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository()
    app.dependency_overrides[get_repository_repository] = lambda: repositories
    app.dependency_overrides[get_parsed_file_repository] = lambda: InMemoryParsedFileRepository()
    app.dependency_overrides[get_dependency_edge_repository] = (
        lambda: InMemoryDependencyEdgeRepository()
    )
    app.dependency_overrides[get_graph_repository] = lambda: graph
    app.dependency_overrides[get_graph_intelligence_repository] = lambda: intelligence

    with TestClient(app) as test_client:
        yield test_client


async def _seed_repository(repositories: InMemoryRepositoryRepository) -> Repository:
    now = datetime.now(UTC)
    repository = Repository(
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
    await repositories.create(repository)
    return repository


def _node(repository_id, kind=GraphNodeKind.SYMBOL) -> GraphNode:
    return GraphNode(id=uuid4(), kind=kind, repository_id=repository_id, properties={})


def _rel(
    repository_id, source_id, target_id, kind=GraphRelationshipKind.CALLS
) -> GraphRelationship:
    return GraphRelationship(
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        repository_id=repository_id,
        dependency_edge_id=None,
        properties={},
    )


def _seed_chain_sync(repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository):
    """A -[CALLS]-> B -[CALLS]-> C -[CALLS]-> D, run synchronously via anyio
    since fixtures/tests here are sync `TestClient`-driven, unlike the async
    unit/integration tests elsewhere in this suite."""
    import anyio

    async def _seed():
        repository = await _seed_repository(repositories)
        a, b, c, d = (_node(repository.id) for _ in range(4))
        rels = (
            _rel(repository.id, a.id, b.id),
            _rel(repository.id, b.id, c.id),
            _rel(repository.id, c.id, d.id),
        )
        await graph.project_repository(repository.id, (a, b, c, d), rels)
        return repository, a, b, c, d

    return anyio.run(_seed)


def _base_url(project_id, repository_id) -> str:
    return f"/api/v1/projects/{project_id}/repositories/{repository_id}"


def test_list_dependencies_returns_downstream(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)
    url = f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{b.id}/dependencies"

    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert {n["node"]["id"] for n in body} == {str(c.id)}


def test_list_dependents_returns_upstream(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)
    url = f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{b.id}/dependents"

    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert {n["node"]["id"] for n in body} == {str(a.id)}


def test_dependencies_unknown_node_returns_404(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, *_ = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/nodes/"
        f"{uuid4()}/dependencies"
    )

    assert response.status_code == 404


def test_dependencies_unknown_repository_returns_404(client: TestClient) -> None:
    response = client.get(f"{_base_url(uuid4(), uuid4())}/graph/nodes/{uuid4()}/dependencies")
    assert response.status_code == 404


def test_impact_defaults_to_upstream(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)
    url = f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{c.id}/impact"

    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert body["direction"] == "upstream"
    assert {n["node"]["id"] for n in body["impacted_nodes"]} == {str(a.id), str(b.id)}


def test_impact_accepts_downstream_direction(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{b.id}/impact",
        params={"direction": "downstream", "depth": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert {n["node"]["id"] for n in body["impacted_nodes"]} == {str(c.id)}


def test_impact_depth_below_one_returns_422(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{b.id}/impact",
        params={"depth": 0},
    )

    assert response.status_code == 422


def test_impact_depth_above_server_ceiling_returns_400(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{b.id}/impact",
        params={"depth": 999},
    )

    assert response.status_code == 400


def test_impact_unknown_node_returns_404(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, *_ = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/nodes/{uuid4()}/impact"
    )

    assert response.status_code == 404


def test_path_found(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/path",
        params={"source_id": str(a.id), "target_id": str(d.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["length"] == 3
    assert [n["id"] for n in body["nodes"]] == [str(a.id), str(b.id), str(c.id), str(d.id)]


def test_path_not_found_is_200_not_404(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/path",
        params={"source_id": str(d.id), "target_id": str(a.id)},  # reverse direction
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["length"] is None


def test_path_unknown_source_returns_404(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/path",
        params={"source_id": str(uuid4()), "target_id": str(d.id)},
    )

    assert response.status_code == 404


def test_path_depth_below_one_returns_422(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/path",
        params={"source_id": str(a.id), "target_id": str(d.id), "depth": 0},
    )

    assert response.status_code == 422


def test_statistics_returns_counts_and_freshness(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(f"{_base_url(repository.project_id, repository.id)}/graph/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 4
    assert body["total_relationships"] == 3
    assert "freshness" in body
    assert len(body["relationships_by_kind"]) == 5  # every kind always present


def test_statistics_unknown_repository_returns_404(client: TestClient) -> None:
    response = client.get(f"{_base_url(uuid4(), uuid4())}/graph/statistics")
    assert response.status_code == 404


def test_statistics_limit_above_server_ceiling_returns_400(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, *_ = _seed_chain_sync(repositories, graph)

    response = client.get(
        f"{_base_url(repository.project_id, repository.id)}/graph/statistics",
        params={"limit": 100000},
    )

    assert response.status_code == 400


def test_insights_returns_structured_body(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository, a, b, c, d = _seed_chain_sync(repositories, graph)

    response = client.get(f"{_base_url(repository.project_id, repository.id)}/graph/insights")

    assert response.status_code == 200
    body = response.json()
    assert "most_connected_files" in body
    assert "dependency_hotspots" in body
    assert "isolated_nodes" in body
    assert "mutual_import_pairs" in body
    assert "unresolved_dependency_count" in body


def test_insights_unknown_repository_returns_404(client: TestClient) -> None:
    response = client.get(f"{_base_url(uuid4(), uuid4())}/graph/insights")
    assert response.status_code == 404


def test_neo4j_unavailable_returns_503(
    client: TestClient,
    repositories: InMemoryRepositoryRepository,
    graph: InMemoryGraphRepository,
    intelligence: InMemoryGraphIntelligenceRepository,
) -> None:
    repository, *_ = _seed_chain_sync(repositories, graph)
    intelligence.available = False

    response = client.get(f"{_base_url(repository.project_id, repository.id)}/graph/statistics")

    assert response.status_code == 503


def test_cross_repository_node_returns_404_for_dependencies(
    client: TestClient, repositories: InMemoryRepositoryRepository, graph: InMemoryGraphRepository
) -> None:
    repository_a, a, *_ = _seed_chain_sync(repositories, graph)
    repository_b, *_ = _seed_chain_sync(repositories, graph)

    # `a` is real, but belongs to repository_a — queried under repository_b.
    response = client.get(
        f"{_base_url(repository_b.project_id, repository_b.id)}/graph/nodes/{a.id}/dependencies"
    )

    assert response.status_code == 404
