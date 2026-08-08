"""Tests for GitRepositorySource.

`validate()` tests never touch the network or a subprocess — pure URL parsing.

`materialize_into()` tests use a *real* `git` binary against local, offline
fixtures (a tiny repo created with `git init` in a tmp dir, or a nonexistent path
to force a real failure) rather than the network or a mocked `git` — GitHub
availability shouldn't gate this suite, but the actual subprocess/argv/exit-code
handling should be exercised for real. The one exception is the timeout path
(`test_materialize_into_times_out_and_cleans_up`), which fakes `subprocess.Popen`
so the test doesn't have to wait out a real multi-second hang to prove the
orchestration (kill -> reap -> cleanup -> raise) is wired correctly.

`_terminate_process_tree` — the actual fix for the reported bug (GitPython's
`kill_after_timeout` uses a POSIX-only process-group kill and raises outright on
Windows) — gets its own test against a real parent+child process pair, since that
mechanism is the whole point of this change and deserves more than a mock.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from forge.domain.errors import SourceImportError, SourceValidationError
from forge.infrastructure.sources import git_source
from forge.infrastructure.sources.git_source import GitRepositorySource, _terminate_process_tree


def _make_source(
    url: str, *, clone_timeout_seconds: int = 30, max_repo_size_bytes: int = 1024 * 1024
) -> GitRepositorySource:
    return GitRepositorySource(
        url, clone_timeout_seconds=clone_timeout_seconds, max_repo_size_bytes=max_repo_size_bytes
    )


# --- validate(): unchanged behavior, still offline, still exercised -------------


def test_accepts_valid_https_url() -> None:
    _make_source("https://github.com/org/repo.git").validate()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/org/repo.git",
        "git://github.com/org/repo.git",
        "ssh://git@github.com/org/repo.git",
        "file:///etc/passwd",
        "ext::sh -c 'touch pwned'",
    ],
)
def test_rejects_disallowed_schemes(url: str) -> None:
    with pytest.raises(SourceValidationError):
        _make_source(url).validate()


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(SourceValidationError):
        _make_source("https://user:secret@github.com/org/repo.git").validate()


def test_rejects_missing_host() -> None:
    with pytest.raises(SourceValidationError):
        _make_source("https:///org/repo.git").validate()


def test_rejects_missing_path() -> None:
    with pytest.raises(SourceValidationError):
        _make_source("https://github.com").validate()


# --- materialize_into(): real `git`, local/offline fixtures ---------------------


@pytest.fixture
def local_git_repo(tmp_path: Path) -> Path:
    """A real, tiny local git repository — clonable by a real `git clone` with no
    network involved, so "successful clone" can be tested for real."""
    repo = tmp_path / "source_repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello forge")
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repo, check=True)
    return repo


def test_materialize_into_clones_a_real_repository(local_git_repo: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _make_source(str(local_git_repo)).materialize_into(workspace)

    assert (workspace / "README.md").read_text() == "hello forge"


def test_materialize_into_raises_on_git_failure_and_cleans_workspace(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SourceImportError, match="Git clone failed"):
        _make_source(str(not_a_repo)).materialize_into(workspace)

    assert not workspace.exists()


def test_materialize_into_enforces_size_limit_after_clone(
    local_git_repo: Path, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SourceImportError, match="exceeding the limit"):
        _make_source(str(local_git_repo), max_repo_size_bytes=0).materialize_into(workspace)

    assert not workspace.exists()


def test_materialize_into_times_out_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fakes `subprocess.Popen` so the test doesn't wait out a real hang — proves
    materialize_into's orchestration (kill -> reap -> remove workspace -> raise)
    without depending on wall-clock timing. The actual kill mechanism this relies
    on is tested for real below, against a real process tree."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class _FakePopen:
        pid = 4294967295  # guaranteed-invalid PID — kill attempts on it are safe no-ops
        returncode = 0

        def __init__(self) -> None:
            self._calls = 0

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            self._calls += 1
            if self._calls == 1:
                raise subprocess.TimeoutExpired(cmd="git", timeout=timeout or 0)
            return b"", b""

    # Only the *first* Popen call (our `git clone`) gets faked. `subprocess.run`
    # (used internally by `_terminate_process_tree`'s Windows `taskkill` path) also
    # goes through `subprocess.Popen` — patching every call would make it try to
    # use `_FakePopen` as a context manager and fail with a TypeError unrelated to
    # anything this test is about, so calls after the first fall through to the
    # real Popen.
    real_popen = subprocess.Popen
    calls = {"n": 0}

    def _fake_popen(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakePopen()
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(git_source.subprocess, "Popen", _fake_popen)

    with pytest.raises(SourceImportError, match="exceeded the timeout"):
        _make_source("https://example.com/org/repo.git", clone_timeout_seconds=1).materialize_into(
            workspace
        )

    assert not workspace.exists()


def test_materialize_into_reports_missing_git_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def _raise_not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(git_source.subprocess, "Popen", _raise_not_found)

    with pytest.raises(SourceImportError, match="Failed to start git"):
        _make_source("https://example.com/org/repo.git").materialize_into(workspace)


# --- _terminate_process_tree(): the actual fix, against a real process tree -----


def test_terminate_process_tree_kills_parent_and_child(tmp_path: Path) -> None:
    """Reproduces why `process.kill()` alone isn't enough: `git clone` over HTTPS
    spawns a `git-remote-https` child process. This test spawns an equivalent
    parent+child pair for real (no git needed to prove the mechanism) and asserts
    `_terminate_process_tree` kills both — the child keeps a heartbeat file growing
    every 50ms until it's killed, so "the file stopped growing" is a portable,
    non-PID-based proof of death on both Windows and POSIX."""
    heartbeat = tmp_path / "heartbeat.txt"
    child_code = (
        "import time\n"
        f"f = open(r'{heartbeat}', 'a')\n"
        "for _ in range(200):\n"
        "    f.write('x'); f.flush(); time.sleep(0.05)\n"
    )
    parent_code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "time.sleep(30)\n"
    )

    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (not heartbeat.exists() or heartbeat.stat().st_size == 0):
        time.sleep(0.05)
    assert heartbeat.exists() and heartbeat.stat().st_size > 0, "child process never started"

    _terminate_process_tree(process)

    size_at_kill = heartbeat.stat().st_size
    time.sleep(1.0)
    size_after_wait = heartbeat.stat().st_size

    assert process.poll() is not None, "parent process was not reaped after being killed"
    assert size_after_wait == size_at_kill, (
        "heartbeat file kept growing after _terminate_process_tree returned — the "
        "child process survived the kill (this is exactly the bug: killing only "
        "the top-level process leaves git's transport-helper child running)"
    )
