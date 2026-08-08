"""Git URL repository source — clones a remote repository into a workspace.

Purpose:       Materialize a git repository, identified by URL, into a workspace
                directory.
Responsibility: Validate the URL is a well-formed, credential-free HTTPS git remote
                before any network call, and perform a shallow, time-bounded clone.
                This is the only place in Forge that shells out to git — `git` is
                invoked as an argv list via `subprocess.Popen` with `shell=False`
                (the default), never as a shell string, so there is no shell command
                to inject into. Beyond that:

                - **Scheme allowlist**: only `https://` is accepted. `file://`
                  would let a "remote" URL read the server's own filesystem;
                  other schemes (`ext::`, `ssh://`, ...) are refused outright.
                - **`--`  before the URL**: stops a URL that happens to start with
                  `-` from being parsed as a `git clone` option.
                - **No embedded credentials**: `https://user:pass@host/...` is
                  rejected rather than accepted-and-stripped, so a credential can
                  never end up transiently in memory here at all.
                - **`GIT_TERMINAL_PROMPT=0`**: a private/inaccessible repo fails
                  fast with an error instead of git hanging on a credential prompt
                  that will never be answered.
                - **Timeout**: bounds total clone time; a slow-loris or oversized
                  remote can't hang an import indefinitely. Implemented with a plain
                  `subprocess.Popen` + `communicate(timeout=...)` rather than
                  GitPython's `Repo.clone_from(..., kill_after_timeout=...)` — that
                  GitPython feature shells out to a POSIX-only process-group kill
                  and raises on Windows ("kill_after_timeout" feature is not
                  supported on Windows"). `_terminate_process_tree` below does the
                  same job (kill the clone and everything it spawned) with a
                  platform branch that actually has a Windows implementation: `git`
                  spawns a transport helper subprocess for HTTPS
                  (`git-remote-https`), so killing only the top-level `git` PID on
                  timeout would leave that helper running and still downloading.
                - **Post-clone size check**: `--depth 1` bounds history, but a
                  single commit can still contain an enormous tree — checked
                  against a configured cap after clone, before the workspace is
                  handed to the metadata scanner.
Depends on:    stdlib `subprocess` only (no GitPython — see the timeout note above
                for why it was dropped from this file specifically).
Depended on by: api/repositories.py (constructs this); called only through
                domain/repository/ports.py::RepositorySource by
                application/repository_import/service.py.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from forge.domain.errors import SourceImportError, SourceValidationError

_ALLOWED_SCHEMES = {"https"}
_HOST_PATTERN = re.compile(r"^[a-zA-Z0-9.-]+$")

# How long to wait for a killed process tree to actually exit before giving up on
# the reap and moving on anyway — the workspace gets removed either way.
_KILL_REAP_TIMEOUT_SECONDS = 5


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
        command = [
            "git",
            "clone",
            "--depth=1",
            "--single-branch",
            "--",
            self._url,
            str(workspace),
        ]
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"

        try:
            # `start_new_session=True` puts the child (and anything it spawns) in
            # its own process group/session on POSIX, and its own process group on
            # Windows (Python 3.11+) — required for `_terminate_process_tree` to be
            # able to kill the whole tree below rather than just this one PID.
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            raise SourceImportError(f"Failed to start git: {exc}") from exc

        try:
            _, stderr = process.communicate(timeout=self._clone_timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            _remove_workspace(workspace)
            raise SourceImportError(
                f"Git clone exceeded the timeout of {self._clone_timeout_seconds}s "
                "and was terminated"
            ) from None

        if process.returncode != 0:
            _remove_workspace(workspace)
            message = stderr.decode("utf-8", errors="replace").strip()
            raise SourceImportError(
                f"Git clone failed: {message or f'git exited with code {process.returncode}'}"
            )

        total_size = sum(f.stat().st_size for f in workspace.rglob("*") if f.is_file())
        if total_size > self._max_repo_size_bytes:
            _remove_workspace(workspace)
            raise SourceImportError(
                f"Cloned repository is {total_size} bytes, exceeding the limit of "
                f"{self._max_repo_size_bytes}"
            )


def _remove_workspace(workspace: Path) -> None:
    """Best-effort remove a rejected/failed clone's workspace.

    Plain `shutil.rmtree(path, ignore_errors=True)` silently leaves files behind
    on Windows: git marks some of its own internal files (pack/idx files under
    `.git/objects`) read-only, and Windows refuses to delete a read-only file
    without clearing that attribute first — `ignore_errors=True` swallows the
    resulting `PermissionError` instead of fixing it, so callers that assumed
    cleanup succeeded (e.g. the workspace-size check re-running against a
    directory that's supposed to be gone) would silently be wrong. `onexc` retries
    each failing removal once after clearing the read-only bit.
    """
    if not workspace.exists():
        return

    def _clear_readonly_and_retry(
        func: Callable[[str], object], path: str, _exc: BaseException
    ) -> None:
        os.chmod(path, stat.S_IWRITE)
        func(path)

    with contextlib.suppress(OSError):
        shutil.rmtree(workspace, onexc=_clear_readonly_and_retry)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill `process` and every descendant it spawned, then reap it.

    A plain `process.kill()` only signals the top-level PID — git's HTTPS
    transport runs as a separate `git-remote-https` child process, which would be
    orphaned (and keep downloading) if only the parent were killed. `taskkill /T`
    walks the real Windows process tree by parent PID, independent of process
    groups; `os.killpg` on POSIX kills the whole group `start_new_session=True`
    put the child in. Guarded with `sys.platform` (not `os.name`) specifically so
    mypy statically excludes the POSIX-only `os.killpg`/`signal.SIGKILL` branch
    when type-checked on Windows, and vice versa — both branches only need to
    typecheck on the platform they actually run on.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        import signal

        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)

    with contextlib.suppress(subprocess.TimeoutExpired, ValueError):
        process.communicate(timeout=_KILL_REAP_TIMEOUT_SECONDS)
