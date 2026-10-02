"""Comprehensive repository-ownership security regression test.

Release Blocker:
    Ensure that no repository-scoped endpoint ever leaks or operates on data
    belonging to another project (IDOR vulnerability).

    When an endpoint under `/projects/{project_id}/repositories/{repository_id}/...`
    is requested with a `project_id` that does NOT own `repository_id`, the system
    must consistently respond with HTTP 404 (Not Found) rather than 403 or 200,
    preventing both data leakage and existence probing across project boundaries.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_project_repository,
    get_repository_repository,
)
from forge.infrastructure.rag.dependencies import get_chunk_repository
from tests.fakes import (
    InMemoryChunkRepository,
    InMemoryDependencyEdgeRepository,
    InMemoryGraphRepository,
    InMemoryParsedFileRepository,
    InMemoryProjectRepository,
    InMemoryRepositoryRepository,
)

_CODE = """
def sample_function():
    return 42
"""


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces"),
        rag_embedding_provider="hashing",
        rag_llm_provider="extractive",
        rag_retrieval_min_score=0.0,
    )

    shared_projects = InMemoryProjectRepository()
    shared_repositories = InMemoryRepositoryRepository()
    shared_parsed_files = InMemoryParsedFileRepository()
    shared_dependency_edges = InMemoryDependencyEdgeRepository()
    shared_graph = InMemoryGraphRepository()
    shared_chunks = InMemoryChunkRepository()

    app.dependency_overrides[get_project_repository] = lambda: shared_projects
    app.dependency_overrides[get_repository_repository] = lambda: shared_repositories
    app.dependency_overrides[get_parsed_file_repository] = lambda: shared_parsed_files
    app.dependency_overrides[get_dependency_edge_repository] = lambda: shared_dependency_edges
    app.dependency_overrides[get_graph_repository] = lambda: shared_graph
    app.dependency_overrides[get_chunk_repository] = lambda: shared_chunks

    with TestClient(app) as test_client:
        yield test_client


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _setup_owned_repository(client: TestClient) -> tuple[str, str, str]:
    """Create project A with repository A, and an unrelated project B.

    Returns (project_a_id, repository_a_id, project_b_id).
    """
    proj_a = client.post("/api/v1/projects", json={"name": "Project A"}).json()
    project_a_id = proj_a["id"]

    repo_a = client.post(
        f"/api/v1/projects/{project_a_id}/repositories/import/zip",
        files={"file": ("code.zip", _zip_bytes({"main.py": _CODE}), "application/zip")},
    ).json()
    repository_a_id = repo_a["id"]

    # Parse so files/symbols exist
    client.post(f"/api/v1/projects/{project_a_id}/repositories/{repository_a_id}/parse")
    client.post(
        f"/api/v1/projects/{project_a_id}/repositories/{repository_a_id}/analyze-dependencies"
    )
    client.post(f"/api/v1/projects/{project_a_id}/repositories/{repository_a_id}/graph/project")
    client.post(f"/api/v1/projects/{project_a_id}/repositories/{repository_a_id}/rag/index")

    proj_b = client.post("/api/v1/projects", json={"name": "Project B"}).json()
    project_b_id = proj_b["id"]

    return project_a_id, repository_a_id, project_b_id


def test_repository_get_under_foreign_project_returns_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    res = client.get(f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}")
    assert res.status_code == 404


def test_parsing_routes_under_foreign_project_return_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    base = f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}"

    assert client.post(f"{base}/parse").status_code == 404
    assert client.get(f"{base}/files").status_code == 404
    assert client.get(f"{base}/symbols").status_code == 404
    dummy_symbol_id = uuid.uuid4()
    assert client.get(f"{base}/symbols/{dummy_symbol_id}").status_code == 404
    assert client.get(f"{base}/parse-errors").status_code == 404


def test_dependencies_routes_under_foreign_project_return_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    base = f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}"

    assert client.post(f"{base}/analyze-dependencies").status_code == 404
    assert client.get(f"{base}/dependencies").status_code == 404


def test_graph_routes_under_foreign_project_return_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    base = f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}"
    dummy_node_id = uuid.uuid4()

    assert client.post(f"{base}/graph/project").status_code == 404
    assert client.get(f"{base}/graph/statistics").status_code == 404
    assert client.get(f"{base}/graph/nodes").status_code == 404
    assert client.get(f"{base}/graph/neighbors/{dummy_node_id}").status_code == 404


def test_graph_intelligence_routes_under_foreign_project_return_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    base = f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}"
    dummy_node_id = uuid.uuid4()

    assert client.get(f"{base}/graph/insights").status_code == 404
    assert client.get(f"{base}/graph/dependencies/{dummy_node_id}").status_code == 404
    assert client.get(f"{base}/graph/dependents/{dummy_node_id}").status_code == 404
    assert client.get(f"{base}/graph/impact/{dummy_node_id}").status_code == 404
    path_params = {"source": str(dummy_node_id), "target": str(dummy_node_id)}
    assert client.get(f"{base}/graph/path", params=path_params).status_code == 404


def test_rag_routes_under_foreign_project_return_404(client: TestClient) -> None:
    _, repo_id, foreign_proj_id = _setup_owned_repository(client)
    base = f"/api/v1/projects/{foreign_proj_id}/repositories/{repo_id}"

    assert client.post(f"{base}/rag/index").status_code == 404
    assert client.get(f"{base}/rag/status").status_code == 404
    ask_payload = {"question": "Where is sample_function?"}
    assert client.post(f"{base}/rag/ask", json=ask_payload).status_code == 404
