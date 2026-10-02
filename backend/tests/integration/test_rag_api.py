"""Integration test for the RAG HTTP surface (Phase 7).

Scope: the full stack through the ASGI app — api -> application -> domain, with
in-memory doubles for Postgres (chunks, repositories, parsed files) and Neo4j
(graph), and the DETERMINISTIC offline providers (hashing embeddings, extractive
LLM) selected via settings. The source reader and workspace are REAL: the zip is
extracted to disk, parsed from disk, and its source re-read from disk during
indexing — so this exercises the genuine import -> parse -> index -> ask flow end
to end, just without a live database or a live model. Real-Ollama coverage lives
in the E2E tests; retrieval-quality thresholds are validated there, which is why
the similarity floor is relaxed here (this test proves wiring, not ranking).

The IDOR regression (a repository reached under a project that does not own it)
is covered here at the HTTP boundary for all three RAG routes — the release
blocker from the Phase 7 brief.
"""

from __future__ import annotations

import io
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

_SEARCH_PY = '''"""Search helpers used across the codebase."""


def linear_search(items, target):
    """Return the index of target in items, or -1 if it is absent."""
    for index, value in enumerate(items):
        if value == target:
            return index
    return -1


def binary_search(sorted_items, target):
    """Return the index of target using binary search, or -1 if absent."""
    low = 0
    high = len(sorted_items) - 1
    while low <= high:
        mid = (low + high) // 2
        if sorted_items[mid] == target:
            return mid
        if sorted_items[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    # Deterministic OFFLINE providers + a real on-disk workspace. Everything the
    # ask flow needs beyond a DB/model is genuine (chunking, retrieval, prompt
    # assembly, citation building).
    app.dependency_overrides[get_settings] = lambda: Settings(
        workspace_root_dir=str(tmp_path / "workspaces"),
        rag_embedding_provider="hashing",
        rag_llm_provider="extractive",
        # Relaxed floor: the hashing double is a weaker signal than nomic-embed;
        # ranking quality is asserted in the real-Ollama E2E, not here.
        rag_retrieval_min_score=0.0,
    )

    # Shared singletons so import/parse/index/ask all see the same data.
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


def _import_and_parse(client: TestClient, files: dict[str, str]) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": "RAG Test"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _zip_bytes(files), "application/zip")},
    ).json()
    assert repository["status"] == "ready"
    parse = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse.status_code == 201
    return project["id"], repository["id"]


def _new_project(client: TestClient) -> str:
    return str(client.post("/api/v1/projects", json={"name": "Other"}).json()["id"])


# --- Happy path: index -> status -> ask -------------------------------------


def test_index_returns_counts(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/index"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == repository_id
    assert body["chunk_count"] >= 2  # at least the two functions
    assert body["embedded_count"] >= 2
    assert body["reused_count"] == 0
    assert body["files_indexed"] == 1
    assert body["embedding_model"] == "hashing"


def test_status_reflects_indexing(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})

    before = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/status"
    ).json()
    assert before["indexed"] is False
    assert before["chunk_count"] == 0

    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/index")

    after = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/status"
    ).json()
    assert after["indexed"] is True
    assert after["chunk_count"] >= 2
    assert after["embedding_model"] == "hashing"


def test_ask_returns_grounded_answer_with_real_sources(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/index")

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "How does binary_search find the index of a target?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_sufficient_evidence"] is True
    assert body["llm_provider"] == "extractive"
    assert body["embedding_model"] == "hashing"
    assert len(body["sources"]) >= 1
    # Every citation resolves to the one real file that exists in this repository.
    assert all(source["path"] == "search.py" for source in body["sources"])
    # The queried symbol is among the cited sources (only a handful of chunks
    # exist, so top-k returns them all — no ranking flakiness).
    cited_symbols = {source["symbol_qualified_name"] for source in body["sources"]}
    assert any(name and "binary_search" in name for name in cited_symbols)
    # Every source carries a real line span.
    for source in body["sources"]:
        assert source["start_line"] >= 1
        assert source["end_line"] >= source["start_line"]


def test_ask_before_indexing_is_explicit_insufficient(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "How does binary_search work?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_sufficient_evidence"] is False
    assert body["sources"] == []
    assert body["answer"]  # a non-empty, explicit "not indexed" message


# --- Errors -----------------------------------------------------------------


def test_index_before_parse_returns_409(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Unparsed"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("upload.zip", _zip_bytes({"search.py": _SEARCH_PY}), "application/zip")},
    ).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/rag/index"
    )

    assert response.status_code == 409  # imported but never parsed


def test_ask_with_empty_question_returns_422(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})

    response = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": ""},
    )

    assert response.status_code == 422  # AskRequest.question min_length=1


# --- IDOR regression (release blocker): cross-project access is 404 ----------


def test_ask_under_foreign_project_returns_404(client: TestClient) -> None:
    _, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})
    foreign_project_id = _new_project(client)

    response = client.post(
        f"/api/v1/projects/{foreign_project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "How does binary_search work?"},
    )

    assert response.status_code == 404


def test_status_under_foreign_project_returns_404(client: TestClient) -> None:
    project_id, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/index")
    foreign_project_id = _new_project(client)

    response = client.get(
        f"/api/v1/projects/{foreign_project_id}/repositories/{repository_id}/rag/status"
    )

    assert response.status_code == 404


def test_index_under_foreign_project_returns_404(client: TestClient) -> None:
    _, repository_id = _import_and_parse(client, {"search.py": _SEARCH_PY})
    foreign_project_id = _new_project(client)

    response = client.post(
        f"/api/v1/projects/{foreign_project_id}/repositories/{repository_id}/rag/index"
    )

    assert response.status_code == 404
