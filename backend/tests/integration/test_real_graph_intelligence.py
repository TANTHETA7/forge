"""The real end-to-end Phase 6 test: real ZIP import (Phase 2) -> real
`/parse` (Phase 3) -> real `/analyze-dependencies` (Phase 4) -> real
`/graph/project` (Phase 5) -> real Phase 6 code-intelligence queries -> real
Neo4j -> real API responses — nothing in this file is mocked or faked. Uses
the shared `postgres_schema`/`neo4j_graph` fixtures from
tests/integration/conftest.py.

Fixture repository — identical shape to test_real_graph_projection.py's own
(Python + TypeScript), reused here rather than re-invented, since it already
exercises exactly what Phase 6 needs:

- `pkg/base.py` / `pkg/dog.py`: `Dog(Animal)` — a resolved INHERITS edge, and
  `self.speak()` — an UNRESOLVED CALLS edge (the documented one-level-only
  self/this-call limitation — see docs/architecture/06-code-intelligence.md,
  "Impact analysis"). `Animal.speak` therefore ends up with zero real-kind
  degree — an isolated symbol.
- `pkg/utils.py` / `main.py`: a resolved IMPORTS edge and a resolved CALLS
  edge (`run()` calls `helper()`) — a short, deterministic dependency chain
  for dependencies/dependents/impact/path queries.
- `pkg/circ_a.py` <-> `pkg/circ_b.py`: a circular import pair — the direct
  A<->B mutual-IMPORTS insight case.
- `pkg/__init__.py`: never imports or is imported by anything — an isolated
  file.
- `web/base.ts` / `web/button.ts`: the same resolved-IMPORTS/resolved-INHERITS/
  unresolved-CALLS shape in TypeScript, proving every Phase 6 capability is
  language-agnostic.
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
from tests.integration.conftest import DSN_SQLALCHEMY, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER


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


def _build_fixture() -> bytes:
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


def _base_url(project_id: str, repository_id: str) -> str:
    return f"/api/v1/projects/{project_id}/repositories/{repository_id}"


def _find_node(nodes: list[dict], *, path: str | None = None, name: str | None = None) -> dict:
    for node in nodes:
        if path is not None and node["properties"].get("path") == path:
            return node
        if name is not None and node["properties"].get("name") == name:
            return node
    raise AssertionError(f"no node found for path={path!r} name={name!r} in {nodes!r}")


def test_real_code_intelligence_end_to_end(client: TestClient) -> None:
    project_id, repository_id = _import_parse_analyze_project(client, "Intelligence E2E Fixture")
    base = _base_url(project_id, repository_id)

    nodes = client.get(f"{base}/graph/nodes", params={"limit": 100}).json()
    dog_file = _find_node(nodes, path="pkg/dog.py")
    base_file = _find_node(nodes, path="pkg/base.py")
    utils_file = _find_node(nodes, path="pkg/utils.py")
    main_file = _find_node(nodes, path="main.py")
    dog_symbol = _find_node(nodes, name="Dog")
    animal_symbol = _find_node(nodes, name="Animal")
    helper_symbol = _find_node(nodes, name="helper")
    run_symbol = _find_node(nodes, name="run")
    animal_speak_symbol = _find_node(nodes, name="speak")

    # --- Capability 1: dependencies/dependents, matching the brief's own
    # A-CALLS->B-CALLS->C example shape (here: run -CALLS-> helper) ---------
    # NOTE: dependencies/dependents (Capability 1) return neighbors of *any*
    # relationship kind by default, including the structural CONTAINS/DEFINES
    # edges every node has (a symbol's defining file, a file's owning
    # repository) — not just CALLS/IMPORTS/INHERITS. These assertions pass
    # `kind` explicitly to isolate the specific relationship under test.
    helper_dependents = client.get(
        f"{base}/graph/nodes/{helper_symbol['id']}/dependents", params={"kind": "calls"}
    ).json()
    assert {n["node"]["id"] for n in helper_dependents} == {run_symbol["id"]}

    run_dependencies = client.get(
        f"{base}/graph/nodes/{run_symbol['id']}/dependencies", params={"kind": "calls"}
    ).json()
    assert {n["node"]["id"] for n in run_dependencies} == {helper_symbol["id"]}

    dog_dependencies = client.get(
        f"{base}/graph/nodes/{dog_symbol['id']}/dependencies", params={"kind": "inherits"}
    ).json()
    assert {n["node"]["id"] for n in dog_dependencies} == {animal_symbol["id"]}

    dog_file_dependents = client.get(
        f"{base}/graph/nodes/{base_file['id']}/dependents", params={"kind": "imports"}
    ).json()
    assert {n["node"]["id"] for n in dog_file_dependents} == {dog_file["id"]}

    # --- Capability 3: impact analysis — UPSTREAM is the default, matching
    # "what could be affected if this changes" ------------------------------
    animal_impact = client.get(f"{base}/graph/nodes/{animal_symbol['id']}/impact").json()
    assert animal_impact["direction"] == "upstream"
    assert {n["node"]["id"] for n in animal_impact["impacted_nodes"]} == {dog_symbol["id"]}
    assert animal_symbol["id"] not in {
        n["node"]["id"] for n in animal_impact["impacted_nodes"]
    }  # never includes the starting node itself

    helper_impact = client.get(f"{base}/graph/nodes/{helper_symbol['id']}/impact").json()
    assert {n["node"]["id"] for n in helper_impact["impacted_nodes"]} == {run_symbol["id"]}

    # The documented one-level-only self-call limitation: speak() has no
    # CALLS relationship at all (self.speak() never resolved), so its
    # impact is empty even though bark() textually calls it.
    speak_impact = client.get(f"{base}/graph/nodes/{animal_speak_symbol['id']}/impact").json()
    assert speak_impact["impacted_nodes"] == []

    # --- Capability 4: dependency paths — directed shortest path -----------
    main_to_utils = client.get(
        f"{base}/graph/path",
        params={"source_id": main_file["id"], "target_id": utils_file["id"]},
    ).json()
    assert main_to_utils["found"] is True
    assert main_to_utils["length"] == 1

    dog_to_animal = client.get(
        f"{base}/graph/path",
        params={"source_id": dog_symbol["id"], "target_id": animal_symbol["id"]},
    ).json()
    assert dog_to_animal["found"] is True
    assert dog_to_animal["length"] == 1
    assert [n["id"] for n in dog_to_animal["nodes"]] == [dog_symbol["id"], animal_symbol["id"]]

    # No directed path the other way — a real "not found", not an error.
    animal_to_dog = client.get(
        f"{base}/graph/path",
        params={"source_id": animal_symbol["id"], "target_id": dog_symbol["id"]},
    ).json()
    assert animal_to_dog["found"] is False
    assert animal_to_dog["length"] is None

    # --- Capability 5: graph statistics -------------------------------------
    statistics = client.get(f"{base}/graph/statistics").json()
    assert statistics["total_nodes"] == 20  # 1 repository + 9 files + 10 symbols
    assert statistics["total_files"] == 9
    assert statistics["total_symbols"] == 10
    by_kind = {e["kind"]: e["count"] for e in statistics["relationships_by_kind"]}
    assert by_kind["imports"] == 5
    assert by_kind["calls"] == 1
    assert by_kind["inherits"] == 2
    assert by_kind["contains"] == 13
    assert by_kind["defines"] == 10
    assert statistics["freshness"] == "fresh"
    assert statistics["projected_at"] is not None

    # --- Capability 6: repository insights -----------------------------------
    insights = client.get(f"{base}/graph/insights", params={"limit": 100}).json()
    mutual_pairs = {
        frozenset({p["file_a"]["properties"]["path"], p["file_b"]["properties"]["path"]})
        for p in insights["mutual_import_pairs"]
    }
    assert frozenset({"pkg/circ_a.py", "pkg/circ_b.py"}) in mutual_pairs

    isolated_paths = {
        n["properties"].get("path") or n["properties"].get("name")
        for n in insights["isolated_nodes"]
    }
    assert "pkg/__init__.py" in isolated_paths  # never imported, imports nothing
    assert "speak" in isolated_paths  # self.speak() never resolved to a CALLS edge

    hotspot_names = {e["node"]["properties"]["name"] for e in insights["dependency_hotspots"]}
    assert "Dog" in hotspot_names  # INHERITS
    assert "helper" in hotspot_names  # CALLS

    # Phase 4's own unresolved-edge count, read through without duplication.
    assert insights["unresolved_dependency_count"] == 2  # self.speak(), this.render()


def test_cross_repository_isolation_for_intelligence_queries(client: TestClient) -> None:
    project_id_a, repository_id_a = _import_parse_analyze_project(client, "Intel Isolation A")
    project_id_b, repository_id_b = _import_parse_analyze_project(client, "Intel Isolation B")
    base_a = _base_url(project_id_a, repository_id_a)
    base_b = _base_url(project_id_b, repository_id_b)

    nodes_a = client.get(f"{base_a}/graph/nodes", params={"limit": 100}).json()
    node_in_a = _find_node(nodes_a, name="Dog")

    # A node real in repository A must be invisible under repository B.
    response = client.get(f"{base_b}/graph/nodes/{node_in_a['id']}/dependencies")
    assert response.status_code == 404

    response = client.get(f"{base_b}/graph/nodes/{node_in_a['id']}/impact")
    assert response.status_code == 404

    response = client.get(
        f"{base_b}/graph/path", params={"source_id": node_in_a["id"], "target_id": node_in_a["id"]}
    )
    assert response.status_code == 404

    # Statistics/insights never leak the other repository's counts.
    stats_a = client.get(f"{base_a}/graph/statistics").json()
    stats_b = client.get(f"{base_b}/graph/statistics").json()
    assert stats_a["repository_id"] == repository_id_a
    assert stats_b["repository_id"] == repository_id_b
    assert stats_a["total_nodes"] == stats_b["total_nodes"]  # same fixture, independent counts


def test_statistics_freshness_reflects_a_real_reparse(client: TestClient, tmp_path: Path) -> None:
    project_id, repository_id = _import_parse_analyze_project(client, "Freshness Fixture")
    base = _base_url(project_id, repository_id)

    fresh = client.get(f"{base}/graph/statistics").json()
    assert fresh["freshness"] == "fresh"

    # Mutate the real workspace and re-parse — the graph is now provably
    # stale relative to PostgreSQL until `/graph/project` runs again.
    workspace = tmp_path / "workspaces" / project_id / repository_id
    (workspace / "web" / "button.ts").unlink()
    reparsed = client.post(f"{base}/parse")
    assert reparsed.status_code == 201

    stale = client.get(f"{base}/graph/statistics").json()
    assert stale["freshness"] == "stale"

    client.post(f"{base}/analyze-dependencies")
    client.post(f"{base}/graph/project")

    fresh_again = client.get(f"{base}/graph/statistics").json()
    assert fresh_again["freshness"] == "fresh"
