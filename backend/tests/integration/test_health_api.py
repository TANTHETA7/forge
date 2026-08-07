"""Integration test for the health endpoint.

Scope: full stack through the ASGI app — api -> application -> domain — proving
the layers are wired together correctly end to end.
"""

from fastapi.testclient import TestClient

from forge.core.app_factory import create_app
from forge.core.config import Settings


def _client() -> TestClient:
    app = create_app(settings=Settings(environment="test"))
    return TestClient(app)


def test_health_endpoint_returns_200() -> None:
    response = _client().get("/api/v1/health")

    assert response.status_code == 200


def test_health_endpoint_returns_expected_shape() -> None:
    response = _client().get("/api/v1/health")

    body = response.json()
    assert body["state"] == "ok"
    assert body["app_name"] == "Forge"
    assert "version" in body
