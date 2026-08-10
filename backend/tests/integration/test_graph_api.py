"""Integration test for the graph-projection HTTP surface.

Scope: full stack through the ASGI app — api -> application -> domain (fake
persistence for Postgres AND Neo4j) — proving the routers, schemas, and DI
wiring are correct end to end, mirroring test_dependencies_api.py's
established approach. Real-Neo4j coverage lives in
test_neo4j_graph_projection.py and test_real_graph_projection.py instead.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.domain.repository.entities import Repository, RepositorySourceType, RepositoryStatus
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_project_repository,
    get_repository_repository,
)
from tests.fakes import (
    InMemoryDependencyEdgeRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
)


@pytest.fixture
def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


@pytest.fixture
def client(tmp_path: Path, graph: InMemoryGraphRepository) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )

    shared_projects = InMemoryProjectRepository()
    shared_repositories = InMemoryRepositoryRepository()
    shared_parsed_files = InMemoryParsedFileRepository()
    shared_dependency_edges = InMemoryDependencyEdgeRepository()
    app.dependency_overrides[get_project_repository] = lambda: shared_projects
    app.dependency_overrides[get_repository_repository] = lambda: shared_repositories
    app.dependency_overrides[get_parsed_file_repository] = lambda: shared_parsed_files
    app.dependency_overrides[get_dependency_edge_repository] = lambda: shared_dependency_edges
    app.dependency_overrides[get_graph_repository] = lambda: graph

    with TestClient(app) as test_client:
        yield test_client


def _make_zip_bytes() -> bytes:
    # Deliberately just two files, neither defining a symbol — keeps node/
    # relationship counts in the assertions below simple and exact (1
    # repository + 2 file nodes; 2 CONTAINS relationships; 0 DEFINES). Symbol/
    # DEFINES/CALLS/INHERITS mapping is already covered by
    # tests/unit/test_graph_mapping.py — this file only needs to prove the
    # HTTP surface, not re-derive every mapping case.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("utils.py", "# no symbols on purpose\n")
        zf.writestr("main.py", "from .utils import helper\n")
    return buffer.getvalue()


def _import_and_parse_ready_repository(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": "Graph Test"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"
    parse_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse_response.status_code == 201
    return project["id"], repository["id"]


def test_project_returns_201_with_summary(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["repository_id"] == repository_id
    assert body["node_count"] == 3  # repository + 2 files
    assert body["relationship_count"] == 2  # 2 CONTAINS


def test_project_unknown_repository_returns_404(client: TestClient) -> None:
    project_id, _ = _import_and_parse_ready_repository(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/"
        "00000000-0000-0000-0000-000000000000/graph/project"
    )
    assert response.status_code == 404


def test_project_unparsed_repository_returns_409(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Not Parsed"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _make_zip_bytes(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"  # imported, but /parse was never called

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/graph/project"
    )
    assert response.status_code == 409


def test_project_non_ready_repository_returns_409(tmp_path: Path) -> None:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces")
    )
    repositories = InMemoryRepositoryRepository()
    app.dependency_overrides[get_repository_repository] = lambda: repositories
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository()
    app.dependency_overrides[get_parsed_file_repository] = lambda: InMemoryParsedFileRepository()
    app.dependency_overrides[get_dependency_edge_repository] = (
        lambda: InMemoryDependencyEdgeRepository()
    )
    app.dependency_overrides[get_graph_repository] = lambda: InMemoryGraphRepository()

    now = datetime.now(UTC)
    repository_id = uuid4()
    project_id = uuid4()
    importing_repository = Repository(
        id=repository_id,
        project_id=project_id,
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="upload",
        workspace_path=str(tmp_path / "workspaces" / "does-not-exist"),
        status=RepositoryStatus.IMPORTING,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    anyio.run(repositories.create, importing_repository)

    with TestClient(app) as test_client:
        response = test_client.post(
            f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
        )

    assert response.status_code == 409


def test_project_with_neo4j_unavailable_returns_503(
    client: TestClient, graph: InMemoryGraphRepository
) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    graph.available = False

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )

    assert response.status_code == 503


def test_list_nodes_after_projection(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes"
    )

    assert response.status_code == 200
    nodes = response.json()
    assert len(nodes) == 3
    assert {n["kind"] for n in nodes} == {"repository", "file"}


def test_list_nodes_filters_by_kind(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"kind": "file"},
    )

    assert response.status_code == 200
    nodes = response.json()
    assert len(nodes) == 2
    assert all(n["kind"] == "file" for n in nodes)


def test_list_nodes_before_projection_returns_empty_list_not_404(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_nodes_unknown_repository_returns_404(client: TestClient) -> None:
    project_id, _ = _import_and_parse_ready_repository(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/"
        "00000000-0000-0000-0000-000000000000/graph/nodes"
    )
    assert response.status_code == 404


def test_list_dependencies_after_projection(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/dependencies",
        params={"kind": "imports"},
    )

    assert response.status_code == 200
    relationships = response.json()
    assert len(relationships) == 1
    assert relationships[0]["kind"] == "imports"
    assert relationships[0]["dependency_edge_id"] is not None


def test_get_neighbors_returns_connected_nodes(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")
    nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"kind": "repository"},
    ).json()
    repository_node_id = nodes[0]["id"]

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}"
        f"/graph/neighbors/{repository_node_id}"
    )

    assert response.status_code == 200
    neighbors = response.json()
    assert len(neighbors) == 2  # both files
    assert all(n["relationship_kind"] == "contains" for n in neighbors)


def test_get_neighbors_unknown_node_returns_404(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")

    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/neighbors/"
        "00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404


def test_get_neighbors_cross_repository_node_returns_404(client: TestClient) -> None:
    project_id, repository_id_a = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id_a}/graph/project")
    _, repository_id_b = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id_b}/graph/project")

    nodes_a = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id_a}/graph/nodes",
        params={"kind": "repository"},
    ).json()
    node_id_in_a = nodes_a[0]["id"]

    # node_id_in_a is real, but queried under repository_id_b's scope.
    response = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id_b}"
        f"/graph/neighbors/{node_id_in_a}"
    )

    assert response.status_code == 404


def test_reprojection_does_not_duplicate_nodes(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse_ready_repository(client)
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")
    second = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )

    assert second.status_code == 201
    nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes"
    ).json()
    assert len(nodes) == 3  # not duplicated
