"""Repository-ownership FastAPI dependency (release-blocker fix).

Purpose:       Enforce, at the HTTP edge, that a repository addressed as
                `/projects/{project_id}/repositories/{repository_id}/...` actually
                belongs to `{project_id}` — closing the IDOR where a handler
                looked a repository up by id alone and served repository B's data
                through project A's URL with a 200.
Responsibility: Adapt `application/shared.require_owned_repository` into a
                dependency FastAPI can attach to a whole router, so every
                repository-scoped route is guarded uniformly rather than each
                handler remembering to check. Raises `NotFoundError` (-> 404) on a
                mismatch; returns nothing on success.
Depends on:    application/shared.py, infrastructure/persistence/dependencies.py.
Depended on by: core/app_factory.py (attaches this to every repository-scoped
                router), api/repositories.py (guards its `GET /{repository_id}`).

Why a 404 and not a 403: a repository under a different project is treated as
not-found, so the response can't be used to probe which repository ids exist in
projects the caller can't see (see application/shared.py). The check is a single
indexed primary-key lookup; attaching it per-router adds one such lookup per
request, which at Forge's scale is immaterial next to the isolation guarantee it
buys.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends

from forge.application.shared import require_owned_repository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.persistence.dependencies import get_repository_repository


async def verify_repository_ownership(
    project_id: UUID,
    repository_id: UUID,
    repositories: RepositoryRepository = Depends(get_repository_repository),
) -> None:
    """Router dependency: 404 unless `repository_id` belongs to `project_id`.

    `project_id` and `repository_id` are taken from the path (every guarded
    router is mounted under `/projects/{project_id}/repositories/{repository_id}`).
    """
    await require_owned_repository(repositories, project_id, repository_id)
