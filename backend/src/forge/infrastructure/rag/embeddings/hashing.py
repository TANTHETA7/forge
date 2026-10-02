"""Deterministic hashing embedding provider (Phase 7).

Purpose:       Embed text without any model server, deterministically, so the
                entire RAG pipeline — chunking, storage, repository-scoped
                retrieval, grounding — can be unit-tested offline. NOT a
                production path and NOT a stand-in for real semantics: it exists
                so tests don't depend on Ollama being up.
Responsibility: One `EmbeddingProvider` implementation using feature hashing.
                Token-overlap similarity only — two texts sharing tokens score
                higher, which is enough for a test to assert that retrieval picks
                the chunk that shares words with the query.
Depends on:    domain/rag/retrieval.py (normalisation), stdlib hashlib/re.
Depended on by: infrastructure/rag/dependencies.py (only when
                `rag_embedding_provider="hashing"`).

Determinism is the whole point, so hashing uses `hashlib.sha256` (stable across
processes and runs) rather than the builtin `hash()` (per-process salted). The
provider reports its own `model_name` (`"hashing"`), distinct from any real
model, so a stored hashing vector is never reused when the deployment later
switches to a real embedding model.
"""

from __future__ import annotations

import hashlib
import re

from forge.domain.rag.retrieval import normalize_vector

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_MODEL_NAME = "hashing"


class HashingEmbeddingProvider:
    """An offline, deterministic `EmbeddingProvider` using feature hashing into a
    fixed-dimension vector."""

    def __init__(self, *, dimensions: int) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return _MODEL_NAME

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed(text) for text in texts)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed(text)

    def _embed(self, text: str) -> tuple[float, ...]:
        """Hash each token into a signed bucket, accumulate, and L2-normalise."""
        vector = [0.0] * self._dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            # A separate bit picks the sign so unrelated tokens colliding in the
            # same bucket tend to cancel rather than always reinforce.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        return normalize_vector(vector)
