"""Unit tests for the health application service.

Scope: application + domain layers only — no HTTP, no ASGI app, no I/O.
"""

from forge.application.health_service import HealthService
from forge.core.config import Settings
from forge.domain.health import ServiceState


def test_check_reports_ok_state() -> None:
    settings = Settings(app_name="TestForge")
    service = HealthService(settings)

    status = service.check()

    assert status.state is ServiceState.OK


def test_check_reflects_configured_app_name() -> None:
    settings = Settings(app_name="TestForge")
    service = HealthService(settings)

    status = service.check()

    assert status.app_name == "TestForge"


def test_check_returns_a_non_empty_version() -> None:
    service = HealthService(Settings())

    status = service.check()

    assert status.version
