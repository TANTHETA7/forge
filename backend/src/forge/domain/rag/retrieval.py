"""Vector retrieval math (Phase 7).

Purpose:       The pure similarity computation behind repository-scoped vector
                search — normalising vectors and ranking candidate chunk
                embeddings against a query embedding by cosine similarity.
Responsibility: Numeric functions only. No IO, no persistence, no knowledge of
                where the candidates came from — the repository layer supplies an
                already repository-scoped, already-bounded candidate set and this
                module ranks it. Kept pure so ranking is unit-testable without a
                database or a model.

Why cosine here and not a dot product on the assumption of unit vectors: the
embedding providers *do* L2-normalise (via `normalize_vector`) so a dot product
would suffice for them, but computing true cosine makes ranking correct for any
provider — including a test double that returns un-normalised vectors — at
negligible cost (the candidate set is bounded by `rag_retrieval_candidate_limit`).

Depends on:    domain/rag/entities.py, stdlib math.
Depended on by: application/rag/ask_service.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from forge.domain.rag.entities import ChunkEmbedding


def normalize_vector(vector: Sequence[float]) -> tuple[float, ...]:
    """Return `vector` scaled to unit L2 length.

    A zero (or empty) vector is returned unchanged — there is no unit direction
    to scale it to, and dividing by zero would poison the whole index. Callers
    (the embedding providers) apply this before storage so stored vectors are
    unit-length and directly comparable.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(component / norm for component in vector)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors in [-1.0, 1.0].

    Returns 0.0 if the vectors differ in length (a corrupt/mismatched-model
    embedding must not crash retrieval, and an undefined comparison is treated as
    "not similar") or if either has zero magnitude.
    """
    if len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm_sq = 0.0
    right_norm_sq = 0.0
    for left_component, right_component in zip(left, right, strict=True):
        dot += left_component * right_component
        left_norm_sq += left_component * left_component
        right_norm_sq += right_component * right_component
    if left_norm_sq == 0.0 or right_norm_sq == 0.0:
        return 0.0
    return dot / math.sqrt(left_norm_sq * right_norm_sq)


def rank_by_similarity(
    query_embedding: Sequence[float],
    candidates: Sequence[ChunkEmbedding],
    *,
    top_k: int,
) -> list[tuple[UUID, float]]:
    """Return the `top_k` candidates most similar to `query_embedding`, as
    `(chunk_id, score)` pairs sorted by descending score.

    Ties break on `chunk_id` so the ordering is fully deterministic (two chunks
    with identical scores always rank in the same order across runs). `top_k <= 0`
    yields an empty list; fewer than `top_k` candidates yields all of them.
    """
    if top_k <= 0 or not candidates:
        return []
    scored = [
        (candidate.chunk_id, cosine_similarity(query_embedding, candidate.embedding))
        for candidate in candidates
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0].bytes))
    return scored[:top_k]
