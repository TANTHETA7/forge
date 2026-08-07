"""FastAPI application factory.

Purpose:       Assemble the FastAPI app: middleware, routers, startup hooks.
Responsibility: Wiring only — imports every router and mounts it; contains no
                route logic itself. This is the single place that knows the full
                shape of the API surface.
Why it exists: A factory function (rather than a module-level `app = FastAPI()`)
                keeps the app constructible with injected settings, which is what
                makes it possible to spin up isolated app instances in tests.
Depends on:    core/config.py, core/logging.py, api/health.py (and every future
                router).
Depended on by: main.py, tests/conftest.py (future).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forge.api.health import router as health_router
from forge.core.config import Settings, get_settings
from forge.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a configured FastAPI application.

    Args:
        settings: Optional explicit settings, primarily for tests. Defaults to
            the process-wide cached settings.

    Returns:
        A fully wired FastAPI application, not yet running.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        description="Turn Code Into Knowledge.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix=settings.api_v1_prefix)

    return app
