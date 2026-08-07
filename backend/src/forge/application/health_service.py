"""Health application service.

Purpose:       Orchestrate producing a `SystemStatus` for the running process.
Responsibility: One use case — "report current health" — with no HTTP or DB
                concerns. Trivial today; from Phase 2 onward this is where a real
                health check would ping Postgres/Neo4j through their
                infrastructure clients (injected, not imported directly), keeping
                this layer testable without a live database.
Depends on:    domain/health.py, core/config.py.
Depended on by: api/health.py.
"""

from importlib.metadata import PackageNotFoundError, version

from forge.core.config import Settings
from forge.domain.health import ServiceState, SystemStatus


class HealthService:
    """Reports the current health of the Forge backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self) -> SystemStatus:
        """Return the current :class:`SystemStatus`.

        Returns:
            A `SystemStatus` reflecting the service as healthy. Once Postgres and
            Neo4j clients exist (Phase 2+), this method will aggregate their
            individual pings and downgrade to `ServiceState.DEGRADED` if any are
            unreachable.
        """
        return SystemStatus(
            state=ServiceState.OK,
            app_name=self._settings.app_name,
            version=self._app_version(),
        )

    @staticmethod
    def _app_version() -> str:
        try:
            return version("forge-backend")
        except PackageNotFoundError:
            return "0.1.0"
