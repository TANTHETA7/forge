"""Git URL repository source — clones a remote repository into a workspace.

Purpose:       Materialize a git repository, identified by URL, into a workspace
                directory.
Responsibility: Validate the URL is a well-formed, credential-free HTTPS git remote
                before any network call, and perform a shallow, time-bounded clone.
                This is the only place in Forge that shells out to git — GitPython
                invokes `git` via argv (never a shell string), so there is no shell
                command to inject into. Beyond that:

                - **Scheme allowlist**: only `https://` is accepted. `file://`
                  would let a "remote" URL read the server's own filesystem;
                  `ext::`/other GitPython "unsafe protocol" forms can smuggle
                  arbitrary command execution through git's own transport
                  helpers — both are refused outright, and `allow_unsafe_protocols`
                  is deliberately left at its default `False` when cloning.
                - **No embedded credentials**: `https://user:pass@host/...` is
                  rejected rather than accepted-and-stripped, so a credential can
                  never end up transiently in memory here at all.
                - **`GIT_TERMINAL_PROMPT=0`**: a private/inaccessible repo fails
                  fast with an error instead of git hanging on a credential prompt
                  that will never be answered.
                - **`kill_after_timeout`**: bounds total clone time; a slow-loris or
                  oversized remote can't hang an import indefinitely.
                - **Post-clone size check**: `--depth 1` bounds history, but a
                  single commit can still contain an enormous tree — checked
                  against a configured cap after clone, before the workspace is
                  handed to the metadata scanner.
Depends on:    GitPython, domain/errors.py.
Depended on by: api/repositories.py (constructs this); called only through
                domain/repository/ports.py::RepositorySource by
                application/repository_import/service.py.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from git import Repo
from git.exc import GitError

from forge.domain.errors import SourceImportError, SourceValidationError

_ALLOWED_SCHEMES = {"https"}
_HOST_PATTERN = re.compile(r"^[a-zA-Z0-9.-]+$")


class GitRepositorySource:
    """A `RepositorySource` backed by a remote git URL."""

    def __init__(self, url: str, *, clone_timeout_seconds: int, max_repo_size_bytes: int) -> None:
        self._url = url
        self._clone_timeout_seconds = clone_timeout_seconds
        self._max_repo_size_bytes = max_repo_size_bytes

    def validate(self) -> None:
        parts = urlsplit(self._url)
        if parts.scheme not in _ALLOWED_SCHEMES:
            raise SourceValidationError(
                f"Only HTTPS git URLs are supported, got scheme {parts.scheme!r}"
            )
        if not parts.hostname or not _HOST_PATTERN.match(parts.hostname):
            raise SourceValidationError("Git URL has an invalid or missing host")
        if parts.username or parts.password:
            raise SourceValidationError(
                "Embedded credentials in the git URL are not supported — use a "
                "credential-free HTTPS URL"
            )
        if not parts.path or parts.path == "/":
            raise SourceValidationError("Git URL is missing a repository path")

    def materialize_into(self, workspace: Path) -> None:
        try:
            Repo.clone_from(
                self._url,
                workspace,
                depth=1,
                single_branch=True,
                kill_after_timeout=self._clone_timeout_seconds,
                env={"GIT_TERMINAL_PROMPT": "0"},
            )
        except GitError as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            raise SourceImportError(f"Git clone failed: {exc}") from exc

        total_size = sum(f.stat().st_size for f in workspace.rglob("*") if f.is_file())
        if total_size > self._max_repo_size_bytes:
            shutil.rmtree(workspace, ignore_errors=True)
            raise SourceImportError(
                f"Cloned repository is {total_size} bytes, exceeding the limit of "
                f"{self._max_repo_size_bytes}"
            )
