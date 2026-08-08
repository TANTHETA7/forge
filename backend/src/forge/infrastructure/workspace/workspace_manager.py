"""Filesystem-backed workspace isolation.

Purpose:       Give every imported repository its own directory that no other
                project or repository can reach.
Responsibility: Create/delete workspace directories under a single configured root.
                Every path component below the root is a server-generated UUID —
                never derived from request input — which is what makes path
                traversal via a project or repository identifier structurally
                impossible rather than merely validated against. The resolved-path
                check below is defense in depth on top of that, not the primary
                defense.
Depends on:    pathlib, shutil (stdlib), core/config.py.
Depended on by: application/repository_import/service.py, via
                domain/repository/ports.py::WorkspaceProvider.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from forge.core.config import Settings
from forge.domain.errors import WorkspaceError


class FilesystemWorkspaceProvider:
    """A `WorkspaceProvider` backed by a directory tree on local disk."""

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.workspace_root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self, project_id: UUID, repository_id: UUID) -> Path:
        """Create and return a fresh, empty workspace for `repository_id`.

        Raises:
            WorkspaceError: if a workspace already exists for this repository id,
                or if the resolved path somehow falls outside the configured root.
        """
        workspace = self._root / str(project_id) / str(repository_id)
        resolved = workspace.resolve()
        if not resolved.is_relative_to(self._root):
            raise WorkspaceError("Refusing to create a workspace outside the configured root")
        if resolved.exists():
            raise WorkspaceError(f"Workspace already exists: {resolved}")
        resolved.mkdir(parents=True)
        return resolved

    def delete_workspace(self, workspace: Path) -> None:
        """Remove a workspace and everything in it. Silently no-ops if it's already
        gone.

        Raises:
            WorkspaceError: if `workspace` is not inside the configured root — this
                method is never allowed to delete anything else on disk.
        """
        resolved = workspace.resolve()
        if not resolved.is_relative_to(self._root):
            raise WorkspaceError("Refusing to delete a path outside the configured root")
        shutil.rmtree(resolved, ignore_errors=True)
