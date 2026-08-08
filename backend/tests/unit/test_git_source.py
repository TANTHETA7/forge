"""Validation tests for GitRepositorySource.

Only `validate()` is exercised here — it never touches the network, so these tests
run offline. `materialize_into()` (an actual clone) is exercised by
docs/architecture/02-engineering-specification.md §20's planned integration suite,
not here.
"""

from __future__ import annotations

import pytest

from forge.domain.errors import SourceValidationError
from forge.infrastructure.sources.git_source import GitRepositorySource


def _make_source(url: str) -> GitRepositorySource:
    return GitRepositorySource(url, clone_timeout_seconds=30, max_repo_size_bytes=1024 * 1024)


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
