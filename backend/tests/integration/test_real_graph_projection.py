"""The real end-to-end Phase 5 test: real ZIP import (Phase 2) -> real
`/parse` (Phase 3) -> real `/analyze-dependencies` (Phase 4) -> real
`/graph/project` (Phase 5) -> real Neo4j -> real API queries — nothing in
this file is mocked or faked. Uses the shared `postgres_schema`/`neo4j_graph`
fixtures from tests/integration/conftest.py.

Fixture repository (Python + TypeScript, reusing Phase 4's own
mixed-language-fixture style — see test_real_dependency_analysis.py):

- `pkg/base.py` / `pkg/dog.py`: a resolved IMPORTS edge, a resolved INHERITS
  edge (`Dog(Animal)`), and an UNRESOLVED CALLS edge (`self.speak()` — the
  documented one-level-only self/this-call limitation, see
  docs/architecture/04-dependency-analysis.md).
- `pkg/utils.py` / `main.py`: a resolved IMPORTS edge and a resolved CALLS
  edge (`helper()`).
- `pkg/circ_a.py` <-> `pkg/circ_b.py`: a circular import pair — two
  independent resolved IMPORTS edges/relationships.
- `web/base.ts` / `web/button.ts`: the same resolved-IMPORTS/resolved-INHERITS/
  unresolved-CALLS shape as pkg/base.py/pkg/dog.py, in TypeScript
  (`this.render()`), proving the projection is language-agnostic.
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
from tests.integration.conftest import (
    DSN_SQLALCHEMY,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)


@pytest.fixture
def client(postgres_schema: None, neo4j_graph: None, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        postgres_dsn=DSN_SQLALCHEMY,
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        workspace_root_dir=str(tmp_path / "workspaces"),
    )
    with TestClient(app) as test_client:
        yield test_client


def _build_fixture(*, circ_suffix: str = "") -> bytes:
    """`circ_suffix` lets the isolation test build a second, independently-
    importable repository whose file paths still differ (module names must
    be unique within a single ZIP), while producing an identical graph shape."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("pkg/__init__.py", "")
        zf.writestr("pkg/base.py", "class Animal:\n    def speak(self):\n        pass\n")
        zf.writestr(
            "pkg/dog.py",
            "from .base import Animal\n\n\n"
            "class Dog(Animal):\n"
            "    def bark(self):\n"
            "        return self.speak()\n",
        )
        zf.writestr("pkg/utils.py", "def helper():\n    pass\n")
        zf.writestr(
            "main.py",
            "from pkg.utils import helper\n\n\ndef run():\n    helper()\n",
        )
        zf.writestr("pkg/circ_a.py", "from .circ_b import thing_b\n")
        zf.writestr("pkg/circ_b.py", "from .circ_a import thing_a\n")
        zf.writestr("web/base.ts", "class Widget {\n  render(): void {}\n}\n")
        zf.writestr(
            "web/button.ts",
            "import { Widget } from './base';\n\n"
            "class Button extends Widget {\n"
            "  click(): void {\n"
            "    this.render();\n"
            "  }\n"
            "}\n",
        )
    return buffer.getvalue()


def _import_parse_analyze_project(client: TestClient, name: str) -> tuple[str, str]:
    project = client.post("/api/v1/projects", json={"name": name}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("fixture.zip", _build_fixture(), "application/zip")},
    ).json()
    assert repository["status"] == "ready"

    parse_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse_response.status_code == 201
    assert parse_response.json()["error_count"] == 0

    analyze_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/analyze-dependencies"
    )
    assert analyze_response.status_code == 201

    project_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/graph/project"
    )
    assert project_response.status_code == 201

    return project["id"], repository["id"]


def test_real_graph_projection_end_to_end(client: TestClient) -> None:
    project_id, repository_id = _import_parse_analyze_project(client, "Graph E2E Fixture")

    edges = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/dependencies",
        params={"limit": 100},
    ).json()
    resolved_edges = [e for e in edges if e["resolution_status"] == "resolved"]
    unresolved_edges = [e for e in edges if e["resolution_status"] == "unresolved"]
    # 5 resolved imports (.base, pkg.utils, .circ_a, .circ_b, ./base) + 1
    # resolved call (helper()) + 2 resolved inherits (Dog, Button) = 8.
    assert len(resolved_edges) == 8
    # 2 unresolved calls: self.speak(), this.render() (the documented
    # one-level-only limitation, in both languages).
    assert len(unresolved_edges) == 2

    nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"limit": 100},
    ).json()
    relationships = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/dependencies",
        params={"limit": 100},
    ).json()

    # --- nodes exist, one per parsed file/symbol/the repository itself -----
    node_kinds = {n["kind"] for n in nodes}
    assert node_kinds == {"repository", "file", "symbol"}
    assert len([n for n in nodes if n["kind"] == "repository"]) == 1
    assert len([n for n in nodes if n["kind"] == "file"]) == 9  # every parsed file
    file_nodes_by_path = {n["properties"]["path"]: n for n in nodes if n["kind"] == "file"}
    assert "pkg/dog.py" in file_nodes_by_path
    assert "web/button.ts" in file_nodes_by_path

    # --- every RESOLVED Phase 4 edge has a matching Neo4j relationship -----
    relationship_by_dependency_edge_id = {
        r["dependency_edge_id"]: r for r in relationships if r["dependency_edge_id"] is not None
    }
    for edge in resolved_edges:
        matching = relationship_by_dependency_edge_id.get(edge["id"])
        assert matching is not None, f"no graph relationship for resolved edge {edge['id']}"
        expected_source = edge["source_symbol_id"] or edge["source_file_id"]
        expected_target = edge["target_symbol_id"] or edge["target_file_id"]
        assert matching["source_id"] == expected_source
        assert matching["target_id"] == expected_target
        assert matching["kind"] == edge["kind"]

    # --- AMBIGUOUS/UNRESOLVED edges have NO graph relationship -------------
    for edge in unresolved_edges:
        assert edge["id"] not in relationship_by_dependency_edge_id

    # --- structural relationships also present ------------------------------
    relationship_kinds = {r["kind"] for r in relationships}
    assert "contains" in relationship_kinds  # Repository->File, and Class->Method
    assert "defines" in relationship_kinds  # File->Symbol
    assert "imports" in relationship_kinds
    assert "calls" in relationship_kinds
    assert "inherits" in relationship_kinds
    assert "references" not in relationship_kinds  # never produced

    # --- circular import pair: two independent relationships ---------------
    imports_raw = {
        e["raw_target_expression"] for e in resolved_edges if e["kind"] == "imports"
    }
    assert ".circ_b" in imports_raw
    assert ".circ_a" in imports_raw

    # --- the one-level self/this-call limitation, both languages -----------
    calls_by_raw = {
        e["raw_target_expression"]: e for e in unresolved_edges if e["kind"] == "calls"
    }
    assert "self.speak" in calls_by_raw
    assert "this.render" in calls_by_raw


def test_reprojection_is_idempotent(client: TestClient) -> None:
    project_id, repository_id = _import_parse_analyze_project(client, "Idempotency Fixture")
    first_nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"limit": 100},
    ).json()

    second = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )
    assert second.status_code == 201

    second_nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"limit": 100},
    ).json()
    assert len(second_nodes) == len(first_nodes)
    assert {n["id"] for n in second_nodes} == {n["id"] for n in first_nodes}


def test_rebuild_removes_stale_graph_data_after_reparse(client: TestClient, tmp_path: Path) -> None:
    project = client.post("/api/v1/projects", json={"name": "Rebuild Fixture"}).json()
    repository = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("fixture.zip", _build_fixture(), "application/zip")},
    ).json()
    repository_id = repository["id"]
    project_id = project["id"]

    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project")
    first_nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"limit": 100},
    ).json()
    first_file_paths = {n["properties"]["path"] for n in first_nodes if n["kind"] == "file"}
    assert "web/button.ts" in first_file_paths

    # Mutate the real workspace directly on disk — exactly what a re-parse
    # of genuinely changed source reflects — then re-parse/re-analyze/
    # re-project and confirm the removed file's node (and its DEFINES/
    # CALLS/INHERITS relationships) no longer exist. `FilesystemWorkspaceProvider`'s
    # own naming convention (workspace_root_dir/project_id/repository_id) is
    # what makes this path derivable without any new API surface.
    workspace = tmp_path / "workspaces" / project_id / repository_id
    (workspace / "web" / "button.ts").unlink()

    reparsed = client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/parse")
    assert reparsed.status_code == 201
    assert reparsed.json()["file_count"] == 8  # one fewer than the original 9
    client.post(f"/api/v1/projects/{project_id}/repositories/{repository_id}/analyze-dependencies")
    second = client.post(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/project"
    )
    assert second.status_code == 201

    second_nodes = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/nodes",
        params={"limit": 100},
    ).json()
    second_file_paths = {n["properties"]["path"] for n in second_nodes if n["kind"] == "file"}
    assert "web/button.ts" not in second_file_paths
    assert "web/base.ts" in second_file_paths  # untouched files remain

    # The removed file's INHERITS relationship (Button->Widget) must be gone
    # too — not left dangling for a node that no longer exists — while the
    # untouched one (Dog->Animal, in pkg/dog.py) survives the rebuild.
    second_relationships = client.get(
        f"/api/v1/projects/{project_id}/repositories/{repository_id}/graph/dependencies",
        params={"kind": "inherits", "limit": 100},
    ).json()
    assert len(second_relationships) == 1
    assert second_relationships[0]["properties"]["raw_target_expression"] == "Animal"


def test_repository_isolation_across_two_projected_repositories(client: TestClient) -> None:
    project_id_a, repository_id_a = _import_parse_analyze_project(client, "Isolation Fixture A")
    project_id_b, repository_id_b = _import_parse_analyze_project(client, "Isolation Fixture B")

    nodes_a = client.get(
        f"/api/v1/projects/{project_id_a}/repositories/{repository_id_a}/graph/nodes",
        params={"limit": 100},
    ).json()
    nodes_b = client.get(
        f"/api/v1/projects/{project_id_b}/repositories/{repository_id_b}/graph/nodes",
        params={"limit": 100},
    ).json()

    ids_a = {n["id"] for n in nodes_a}
    ids_b = {n["id"] for n in nodes_b}
    assert ids_a.isdisjoint(ids_b)  # deterministic ids fold in repository_id
    assert all(n["repository_id"] == repository_id_a for n in nodes_a)
    assert all(n["repository_id"] == repository_id_b for n in nodes_b)

    # A node from repository A is invisible under repository B's scope.
    some_node_id_in_a = nodes_a[0]["id"]
    cross_repo_response = client.get(
        f"/api/v1/projects/{project_id_b}/repositories/{repository_id_b}"
        f"/graph/neighbors/{some_node_id_in_a}"
    )
    assert cross_repo_response.status_code == 404

    # Re-projecting repository A never touches repository B's graph.
    client.post(f"/api/v1/projects/{project_id_a}/repositories/{repository_id_a}/graph/project")
    nodes_b_after = client.get(
        f"/api/v1/projects/{project_id_b}/repositories/{repository_id_b}/graph/nodes",
        params={"limit": 100},
    ).json()
    assert {n["id"] for n in nodes_b_after} == ids_b
