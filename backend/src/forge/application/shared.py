"""Cross-cutting application helpers shared by multiple services and routers.

Purpose:       House small application-layer helpers that don't belong to any one
                feature package — currently just repository-ownership enforcement.
Responsibility: Pure orchestration over domain ports. No IO of its own, no HTTP,
                no persistence details.
Depends on:    domain/repository/ports.py, domain/repository/entities.py,
                domain/errors.py.
Depended on by: api/ownership.py, application/rag/*.

Why this exists (release-blocker context): every repository-scoped route is
addressed as `/projects/{project_id}/repositories/{repository_id}/...`, but the
handlers historically looked a repository up by `repository_id` alone and never
checked it actually belongs to `project_id`. That is an IDOR — a caller could
read repository B's data through project A's URL and get a 200. `Repository`
already carries its owning `project_id`, so the fix is a single ownership match,
applied uniformly (see api/ownership.py, which turns this into a router
dependency). Repository A must never be reachable through project B.
"""

from __future__ import annotations

from uuid import UUID

from forge.domain.errors import NotFoundError
from forge.domain.repository.entities import Repository
from forge.domain.repository.ports import RepositoryRepository


async def require_owned_repository(
    repositories: RepositoryRepository,
    project_id: UUID,
    repository_id: UUID,
) -> Repository:
    """Return the repository `repository_id` iff it exists AND belongs to
    `project_id`; otherwise raise `NotFoundError`.

    A repository that exists under a *different* project is treated as
    not-found, never as forbidden — a 404 (not a 403) so the response can't be
    used to probe which repository ids exist under projects the caller can't
    see (mirrors the graph layer's own cross-repository isolation stance).
    """
    repository = await repositories.get_by_id(repository_id)
    if repository is None or repository.project_id != project_id:
        raise NotFoundError(
            f"Repository {repository_id} not found in project {project_id}"
        )
    return repository
