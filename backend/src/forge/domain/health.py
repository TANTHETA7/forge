"""Health domain model.

Purpose:       Define what "system status" means, independent of HTTP or transport.
Responsibility: A single immutable value object, `SystemStatus`.
Why it exists: Proves the domain layer's rule for this codebase — pure Python,
                zero framework imports (no FastAPI, no Pydantic) — on the smallest
                possible slice, before real domain models (Repository, Module,
                Function, ...) land in Phase 2+.
Depends on:    stdlib only.
Depended on by: application/health_service.py.
"""

from dataclasses import dataclass
from enum import StrEnum


class ServiceState(StrEnum):
    """Possible states of the Forge service."""

    OK = "ok"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class SystemStatus:
    """Immutable snapshot of the running service's health.

    Attributes:
        state: Overall service state.
        app_name: Name of the running application, for display purposes.
        version: Application version string.
    """

    state: ServiceState
    app_name: str
    version: str
