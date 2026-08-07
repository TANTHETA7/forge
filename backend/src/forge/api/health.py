"""Health API router.

Purpose:       Expose `GET /health` over HTTP.
Responsibility: Translate between HTTP (FastAPI) and the application layer only —
                no business logic lives here.
Depends on:    application/health_service.py, api/schemas.py, core/config.py.
Depended on by: core/app_factory.py (registers this router).
"""

from fastapi import APIRouter, Depends

from forge.api.schemas import HealthResponse
from forge.application.health_service import HealthService
from forge.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


def get_health_service(settings: Settings = Depends(get_settings)) -> HealthService:
    """FastAPI dependency that constructs a :class:`HealthService`."""
    return HealthService(settings)


@router.get("/health", response_model=HealthResponse)
def get_health(service: HealthService = Depends(get_health_service)) -> HealthResponse:
    """Report whether the Forge backend is up and which version is running."""
    status = service.check()
    return HealthResponse(
        state=status.state.value,
        app_name=status.app_name,
        version=status.version,
    )
