"""Real end-to-end RAG and Code Intelligence test (Phase 7).

Stack under test:
- Real PostgreSQL (chunk and vector storage in code_chunks table)
- Real Neo4j (graph nodes and relationships for bounded expansion)
- Real Ollama:
    - nomic-embed-text: embeddings provider
    - qwen2.5-coder:3b: LLM chat provider
- Real repository source files (Python and TypeScript)
- Real parsing (Tree-sitter)
- Real dependency analysis
- Real graph projection
- Real RAG indexing (batch embeddings, content hashing)
- Real RAG retrieval (cosine similarity ranking + graph expansion)
- Real grounded answering and real citations
- Real insufficient-evidence handling
- Real repository ownership security enforcement (IDOR protection)
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings, get_settings
from tests.integration.conftest import (
    DSN_SQLALCHEMY,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)


def _ollama_ready() -> bool:
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        if response.status_code != 200:
            return False
        models = [m["name"] for m in response.json().get("models", [])]
        has_embed = any("nomic-embed-text" in m for m in models)
        has_llm = any("qwen2.5-coder" in m for m in models)
        return has_embed and has_llm
    except Exception:
        return False


_SKIP_OLLAMA = not _ollama_ready()


@pytest.fixture
def client(postgres_schema: None, neo4j_graph: None, tmp_path: Path) -> Iterator[TestClient]:
    if _SKIP_OLLAMA:
        pytest.skip("Ollama not running or missing nomic-embed-text / qwen2.5-coder:3b")

    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        postgres_dsn=DSN_SQLALCHEMY,
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        workspace_root_dir=str(tmp_path / "workspaces"),
        rag_embedding_provider="ollama",
        rag_embedding_model="nomic-embed-text",
        rag_llm_provider="ollama",
        rag_llm_model="qwen2.5-coder:3b",
        rag_retrieval_min_score=0.35,
    )
    with TestClient(app) as test_client:
        yield test_client


def _build_repo_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "geometry/shapes.py",
            '''"""Shape definitions and area calculations."""
import math


class Circle:
    """Represents a geometric circle."""

    def __init__(self, radius: float) -> None:
        self.radius = radius

    def calculate_area(self) -> float:
        """Calculate and return the area of the circle using radius squared."""
        return math.pi * (self.radius ** 2)

    def calculate_perimeter(self) -> float:
        """Calculate the circumference of the circle."""
        return 2 * math.pi * self.radius


def create_unit_circle() -> Circle:
    """Factory creating a circle with radius 1.0."""
    return Circle(radius=1.0)
''',
        )
        archive.writestr(
            "geometry/calculator.py",
            '''"""High-level calculation utilities."""
from geometry.shapes import Circle, create_unit_circle


def compute_standard_area() -> float:
    """Compute standard unit circle area by delegating to create_unit_circle."""
    circle = create_unit_circle()
    return circle.calculate_area()
''',
        )
    return buffer.getvalue()


def test_real_rag_end_to_end_lifecycle(client: TestClient) -> None:
    # 1. Project & Repository creation
    project = client.post("/api/v1/projects", json={"name": "Real RAG Project"}).json()
    project_id = project["id"]

    import_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/import/zip",
        files={"file": ("repo.zip", _build_repo_zip(), "application/zip")},
    )
    assert import_resp.status_code == 201
    repository_id = import_resp.json()["id"]

    # 2. Parse & Analyze & Graph Project
    parse_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse"
    )
    assert parse_resp.status_code == 201

    analysis_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies"
    )
    assert analysis_resp.status_code == 201

    graph_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )
    assert graph_resp.status_code == 201

    # 3. Check unindexed status
    status_before = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/status"
    ).json()
    assert status_before["indexed"] is False
    assert status_before["chunk_count"] == 0

    # 4. Trigger Real Indexing with nomic-embed-text
    index_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/index"
    )
    assert index_resp.status_code == 200
    index_data = index_resp.json()
    assert index_data["chunk_count"] > 0
    assert index_data["embedded_count"] > 0
    assert index_data["files_indexed"] == 2
    assert index_data["embedding_model"] == "nomic-embed-text"

    # 5. Check indexed status
    status_after = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/status"
    ).json()
    assert status_after["indexed"] is True
    assert status_after["chunk_count"] == index_data["chunk_count"]

    # 6. Ask Grounded Question with real Ollama Qwen 2.5 Coder
    ask_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "How does Circle calculate its area?"},
    )
    assert ask_resp.status_code == 200
    answer_data = ask_resp.json()
    assert answer_data["has_sufficient_evidence"] is True
    assert len(answer_data["sources"]) > 0
    answer_lower = answer_data["answer"].lower()
    assert "calculate_area" in answer_lower or "radius" in answer_lower

    # Verify real source citations
    top_source = answer_data["sources"][0]
    assert "shapes.py" in top_source["path"]
    assert top_source["start_line"] > 0
    assert top_source["end_line"] >= top_source["start_line"]
    assert top_source["score"] >= 0.35

    # 6b. Ask Exact Symbol Question (RAG V2 Hybrid Retrieval)
    symbol_ask_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "Where is create_unit_circle defined?"},
    )
    assert symbol_ask_resp.status_code == 200
    symbol_data = symbol_ask_resp.json()
    assert symbol_data["has_sufficient_evidence"] is True
    assert len(symbol_data["sources"]) > 0
    top_symbol_source = symbol_data["sources"][0]
    assert "shapes.py" in top_symbol_source["path"]
    assert top_symbol_source["symbol_qualified_name"] == "create_unit_circle"

    # 7. Ask Insufficient Evidence question
    insufficient_resp = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "What is the recipe for chocolate chip cookies?"},
    )
    assert insufficient_resp.status_code == 200
    insufficient_data = insufficient_resp.json()
    assert insufficient_data["has_sufficient_evidence"] is False
    assert len(insufficient_data["sources"]) == 0

    # 8. Verify Cross-Project Security Isolation
    other_project = client.post(
        "/api/v1/projects", json={"name": "Attacker Project"}
    ).json()
    other_project_id = other_project["id"]

    idor_ask = client.post(
        f"/api/v1/projects/{other_project_id}/repositories/{repository_id}/rag/ask",
        json={"question": "How does Circle calculate its area?"},
    )
    assert idor_ask.status_code == 404
