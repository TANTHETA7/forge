"""The real end-to-end Phase 3 test: real ZIP import (Phase 2, unmodified) -> real
file discovery -> real tree-sitter parsing -> real PostgreSQL persistence, for a
fixture repository with nested directories, mixed Python/JavaScript/TypeScript
files, duplicate-named symbols across files, a binary file, and an unsupported
file type — nothing in this file is mocked or faked.

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


def _build_fixture_repository() -> bytes:
    """A small, deliberately mixed repository:

    - nested directories (src/, src/lib/, src/lib/deep/)
    - Python, JavaScript, and TypeScript source
    - two files that each define a function named `helper` (different languages
      even) — the "duplicate symbol names in different files" requirement
    - a binary file (should be silently skipped, not errored)
    - an unsupported text file (README — silently skipped, not errored)
    - an empty file
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("README.md", "# Fixture repo")
        zf.writestr("empty.py", "")
        zf.writestr(
            "src/models.py",
            "class User:\n"
            "    def __init__(self, name: str):\n"
            "        self.name = name\n\n"
            "    def helper(self):\n"
            "        return self.name\n",
        )
        zf.writestr("src/lib/utils.py", "def helper():\n    return 1\n")
        zf.writestr(
            "src/lib/deep/component.tsx",
            "export function Widget(props: { label: string }): JSX.Element {\n"
            "  return <div>{props.label}</div>;\n"
            "}\n",
        )
        zf.writestr(
            "src/app.ts",
            "import { Widget } from './lib/deep/component';\n\n"
            "class App {\n"
            "  helper(): string {\n"
            "    return 'app';\n"
            "  }\n"
            "}\n",
        )
        zf.writestr("assets/logo.png", b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03binary-content-here")
    return buffer.getvalue()


def test_real_repository_parses_end_to_end_into_postgres(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Fixture Repo"}).json()

    import_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/import/zip",
        files={"file": ("fixture.zip", _build_fixture_repository(), "application/zip")},
    )
    assert import_response.status_code == 201
    repository = import_response.json()
    assert repository["status"] == "ready"

    parse_response = client.post(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse"
    )
    assert parse_response.status_code == 201
    summary = parse_response.json()

    # 4 real source files: models.py, utils.py, component.tsx, app.ts.
    # empty.py is discovered and parsed too (a real, empty, valid file) — 5 total.
    assert summary["file_count"] == 5
    assert summary["error_count"] == 0

    files = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/files"
    ).json()
    paths = {f["path"] for f in files}
    assert paths == {
        "empty.py",
        "src/models.py",
        "src/lib/utils.py",
        "src/lib/deep/component.tsx",
        "src/app.ts",
    }
    # README.md and assets/logo.png are absent — unsupported/binary, silently
    # skipped, never persisted as parsed files or errors.
    assert "README.md" not in paths
    assert "assets/logo.png" not in paths

    languages = {f["path"]: f["language"] for f in files}
    assert languages["src/models.py"] == "python"
    assert languages["src/lib/utils.py"] == "python"
    assert languages["src/lib/deep/component.tsx"] == "typescript"
    assert languages["src/app.ts"] == "typescript"

    # Duplicate symbol names in different files: three distinct `helper` symbols
    # (User.helper method, top-level helper function, App.helper method), each
    # with a stable, distinct id.
    helpers = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/symbols",
        params={"limit": 100},
    ).json()
    helper_symbols = [s for s in helpers if s["name"] == "helper"]
    assert len(helper_symbols) == 3
    assert len({s["id"] for s in helper_symbols}) == 3

    # Nested-class relationship survived the full round trip through the API and
    # real Postgres: the User.helper method has a parent_symbol_id pointing at
    # the User class symbol.
    method_helper = next(s for s in helper_symbols if s["kind"] == "method")
    assert method_helper["parent_symbol_id"] is not None

    # Source locations are real and non-trivial (not all zeros/defaults).
    assert method_helper["start_line"] > 1

    errors = client.get(
        f"/api/v1/projects/{project['id']}/repositories/{repository['id']}/parse-errors"
    ).json()
    assert errors == []
