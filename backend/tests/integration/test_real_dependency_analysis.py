"""The real end-to-end Phase 4 tests: real ZIP import (Phase 2) -> real `/parse`
(Phase 3) -> real `/analyze-dependencies` (Phase 4) -> real PostgreSQL
persistence -> real API queries — nothing in this file is mocked or faked.

Two tests, deliberately kept separate:

- `test_real_python_import_analysis_end_to_end` — the original, narrower slice-1
  fixture (Python imports only: relative, absolute dotted, external/unresolved,
  a circular pair). Left in place as a focused regression anchor for IMPORTS
  resolution specifically.
- `test_real_mixed_language_dependency_analysis_end_to_end` — the full brief:
  multiple Python *and* JS/TS files, an aliased import, function calls, method
  calls, class inheritance, a genuinely ambiguous reference (two wildcard
  imports defining the same name), several genuinely unresolved references
  (including the documented "one level only" self/this-call limitation — see
  docs/architecture/04-dependency-analysis.md, "Risks / limitations"), and a
  circular import pair — then verifies re-running analysis does not duplicate
  edges.

Uses the shared `postgres_schema` fixture from tests/integration/conftest.py.
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
from tests.integration.conftest import DSN_SQLALCHEMY


@pytest.fixture
def client(postgres_schema: None, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(settings=Settings(environment="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        postgres_dsn=DSN_SQLALCHEMY,
        workspace_root_dir=str(tmp_path / "workspaces"),
    )
    with TestClient(app) as test_client:
        yield test_client


def _build_python_imports_fixture() -> bytes:
    """A small, deliberately mixed repository:

    - a relative import (pkg/utils.py -> pkg/models.py)
    - an absolute dotted import (main.py -> pkg/utils.py)
    - a genuinely unresolvable external import (main.py -> "external_thing")
    - a circular import pair (pkg/service_a.py <-> pkg/service_b.py) — proving
      resolution handles a cycle with no special-casing (see
      docs/architecture/04-dependency-analysis.md, "Resolution strategy").
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("pkg/__init__.py", "")
        zf.writestr("pkg/models.py", "class User:\n    pass\n")
        zf.writestr("pkg/utils.py", "from .models import User\n")
        zf.writestr("pkg/service_a.py", "from .service_b import thing_b\n")
        zf.writestr("pkg/service_b.py", "from .service_a import thing_a\n")
        zf.writestr("main.py", "from pkg.utils import helper\nimport external_thing\n")
    return buffer.getvalue()


def test_real_python_import_analysis_end_to_end(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Dependency Fixture"}).json()

    import_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("fixture.zip", _build_python_imports_fixture(), "application/zip")},
    )
    assert import_response.status_code == 201
    repository = import_response.json()
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
    summary = analyze_response.json()

    # 5 imports total: pkg/utils(1) + pkg/service_a(1) + pkg/service_b(1) + main.py(2)
    assert summary["edge_count"] == 5
    assert summary["resolved_count"] == 4
    assert summary["unresolved_count"] == 1
    assert summary["ambiguous_count"] == 0

    edges = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/dependencies"
    ).json()
    assert len(edges) == 5
    assert all(e["kind"] == "imports" for e in edges)

    by_raw = {e["raw_target_expression"]: e for e in edges}

    # Relative import resolved to a specific target file.
    assert by_raw[".models"]["resolution_status"] == "resolved"
    assert by_raw[".models"]["target_file_id"] is not None

    # Absolute dotted import resolved.
    assert by_raw["pkg.utils"]["resolution_status"] == "resolved"

    # Genuinely external import — unresolved, not silently dropped or guessed.
    assert by_raw["external_thing"]["resolution_status"] == "unresolved"
    assert by_raw["external_thing"]["target_file_id"] is None
    assert by_raw["external_thing"]["detail"] is not None

    # Circular import pair: both directions represented as independent
    # resolved edges, no cycle-detection special-casing needed.
    assert by_raw[".service_b"]["resolution_status"] == "resolved"
    assert by_raw[".service_a"]["resolution_status"] == "resolved"

    # Re-running analysis does not duplicate edges (idempotent, deterministic ids).
    second_analyze = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/analyze-dependencies"
    )
    assert second_analyze.status_code == 201
    edges_after_rerun = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/dependencies"
    ).json()
    assert len(edges_after_rerun) == 5
    assert {e["id"] for e in edges_after_rerun} == {e["id"] for e in edges}


def _build_mixed_language_fixture() -> bytes:
    """A deliberately rich, mixed-language repository exercising every category
    the brief asks for:

    Python:
    - pkg/dog.py -> pkg/base.py: a resolved relative import, class
      inheritance (Dog(Animal)), and a self.speak() call that is
      UNRESOLVED -- speak is defined on Animal, not Dog itself, and
      resolution deliberately does not walk the inheritance chain (see
      docs/architecture/04-dependency-analysis.md, "Risks / limitations").
    - main.py: two wildcard imports (pkg.helpers_a, pkg.helpers_b) that
      both define shared_name -- calling it is AMBIGUOUS, not guessed. A
      separate bare aliased import (import pkg.helpers_a as helpers_a) lets
      helpers_a.shared_name() resolve unambiguously via the alias. A bare
      unresolved_call() and a bare import unknown_external_pkg are both
      genuinely UNRESOLVED.
    - pkg/circ_a.py <-> pkg/circ_b.py: a circular import pair.

    JavaScript/TypeScript:
    - web/button.ts -> web/base.ts: a resolved relative import, class
      inheritance (Button extends Widget), and a this.render() call that is
      UNRESOLVED for the same one-level-only reason as self.speak() above.
    - web/app.js -> web/utils.js: a namespace-import alias
      (import * as utils from './utils'), and utils.helper() resolves
      through that alias. unknownFn() is UNRESOLVED.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # Python
        zf.writestr("pkg/__init__.py", "")
        zf.writestr("pkg/base.py", "class Animal:\n    def speak(self):\n        pass\n")
        zf.writestr(
            "pkg/dog.py",
            "from .base import Animal\n\n\n"
            "class Dog(Animal):\n"
            "    def bark(self):\n"
            "        return self.speak()\n",
        )
        zf.writestr("pkg/helpers_a.py", "def shared_name():\n    return 'a'\n")
        zf.writestr("pkg/helpers_b.py", "def shared_name():\n    return 'b'\n")
        zf.writestr("pkg/circ_a.py", "from .circ_b import thing_b\n")
        zf.writestr("pkg/circ_b.py", "from .circ_a import thing_a\n")
        zf.writestr(
            "main.py",
            "from pkg.helpers_a import *\n"
            "from pkg.helpers_b import *\n"
            "import pkg.helpers_a as helpers_a\n"
            "import unknown_external_pkg\n\n\n"
            "def run():\n"
            "    shared_name()\n"
            "    helpers_a.shared_name()\n"
            "    unresolved_call()\n",
        )
        # JavaScript/TypeScript
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
        zf.writestr("web/utils.js", "function helper() {}\n")
        zf.writestr(
            "web/app.js",
            "import * as utils from './utils';\n\n"
            "function main() {\n"
            "  utils.helper();\n"
            "  unknownFn();\n"
            "}\n",
        )
    return buffer.getvalue()


def test_real_mixed_language_dependency_analysis_end_to_end(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Mixed Language Fixture"}).json()

    import_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("fixture.zip", _build_mixed_language_fixture(), "application/zip")},
    )
    assert import_response.status_code == 201
    repository = import_response.json()
    assert repository["status"] == "ready"

    parse_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse_response.status_code == 201
    assert parse_response.json()["error_count"] == 0
    assert parse_response.json()["file_count"] == 12

    analyze_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/analyze-dependencies"
    )
    assert analyze_response.status_code == 201
    summary = analyze_response.json()

    assert summary["edge_count"] == 18
    assert summary["resolved_count"] == 12
    assert summary["ambiguous_count"] == 1
    assert summary["unresolved_count"] == 5

    edges = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/dependencies",
        params={"limit": 100},
    ).json()
    assert len(edges) == 18

    by_kind: dict[str, list[dict]] = {"imports": [], "calls": [], "inherits": []}
    for edge in edges:
        by_kind[edge["kind"]].append(edge)
    assert len(by_kind["imports"]) == 9
    assert len(by_kind["calls"]) == 7
    assert len(by_kind["inherits"]) == 2

    # --- inheritance, both languages -----------------------------------
    for edge in by_kind["inherits"]:
        assert edge["resolution_status"] == "resolved"
    assert {e["raw_target_expression"] for e in by_kind["inherits"]} == {"Animal", "Widget"}

    # --- the "one level only" self/this-call limitation, both languages -
    calls_by_raw: dict[str, list[dict]] = {}
    for edge in by_kind["calls"]:
        calls_by_raw.setdefault(edge["raw_target_expression"], []).append(edge)
    assert all(e["resolution_status"] == "unresolved" for e in calls_by_raw["self.speak"])
    assert all(e["resolution_status"] == "unresolved" for e in calls_by_raw["this.render"])

    # --- ambiguous: two wildcard imports both defining shared_name ------
    ambiguous_edges = [e for e in edges if e["resolution_status"] == "ambiguous"]
    assert len(ambiguous_edges) == 1
    assert ambiguous_edges[0]["raw_target_expression"] == "shared_name"
    assert ambiguous_edges[0]["kind"] == "calls"

    # --- the SAME name resolves unambiguously through an explicit alias -
    aliased_calls = calls_by_raw["helpers_a.shared_name"]
    assert len(aliased_calls) == 1
    assert aliased_calls[0]["resolution_status"] == "resolved"

    # --- namespace-import alias resolution (JS) --------------------------
    assert all(e["resolution_status"] == "resolved" for e in calls_by_raw["utils.helper"])

    # --- genuinely unresolved calls, not silently dropped ----------------
    assert all(e["resolution_status"] == "unresolved" for e in calls_by_raw["unresolved_call"])
    assert all(e["resolution_status"] == "unresolved" for e in calls_by_raw["unknownFn"])

    # --- circular import pair: two independent resolved edges ------------
    import_raw = {e["raw_target_expression"] for e in by_kind["imports"]}
    assert ".circ_b" in import_raw
    assert ".circ_a" in import_raw
    circ_edges = [
        e for e in by_kind["imports"] if e["raw_target_expression"] in (".circ_a", ".circ_b")
    ]
    assert all(e["resolution_status"] == "resolved" for e in circ_edges)

    # --- filtering by resolution_status works end to end ------------------
    unresolved_via_api = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/dependencies",
        params={"resolution_status": "unresolved", "limit": 100},
    ).json()
    assert len(unresolved_via_api) == 5

    # --- re-running analysis does not duplicate edges (idempotent) --------
    second_analyze = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/analyze-dependencies"
    )
    assert second_analyze.status_code == 201
    assert second_analyze.json()["edge_count"] == 18
    edges_after_rerun = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/dependencies",
        params={"limit": 100},
    ).json()
    assert len(edges_after_rerun) == 18
    assert {e["id"] for e in edges_after_rerun} == {e["id"] for e in edges}
