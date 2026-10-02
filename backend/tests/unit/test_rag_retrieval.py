"""Unit tests for the pure vector-retrieval math (Phase 7).

Scope: `normalize_vector`, `cosine_similarity`, and `rank_by_similarity` — the
ranking core that decides which chunks become evidence. No IO. These pin the
numerical contracts the ask-service depends on: normalized vectors so cosine is
a dot product, defensive zeros on degenerate input (never a crash mid-query),
and a total, deterministic ordering (stable citations, reproducible answers).
"""

from __future__ import annotations

import math
from uuid import UUID

from forge.domain.rag.entities import ChunkEmbedding
from forge.domain.rag.retrieval import (
    cosine_similarity,
    normalize_vector,
    rank_by_similarity,
)


def _uuid(n: int) -> UUID:
    return UUID(int=n)


def _candidate(n: int, embedding: tuple[float, ...]) -> ChunkEmbedding:
    return ChunkEmbedding(chunk_id=_uuid(n), embedding=embedding)


def test_normalize_vector_returns_unit_length() -> None:
    normalized = normalize_vector((3.0, 4.0))
    assert math.isclose(math.hypot(*normalized), 1.0, rel_tol=1e-9)
    assert math.isclose(normalized[0], 0.6, rel_tol=1e-9)
    assert math.isclose(normalized[1], 0.8, rel_tol=1e-9)


def test_normalize_zero_vector_is_returned_unchanged() -> None:
    # No division by zero — a zero embedding stays zero rather than exploding.
    assert normalize_vector((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)


def test_normalize_empty_vector_is_returned_unchanged() -> None:
    assert normalize_vector(()) == ()


def test_cosine_of_identical_direction_is_one() -> None:
    assert math.isclose(cosine_similarity((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)), 1.0, rel_tol=1e-9)


def test_cosine_of_orthogonal_vectors_is_zero() -> None:
    assert math.isclose(cosine_similarity((1.0, 0.0), (0.0, 1.0)), 0.0, abs_tol=1e-9)


def test_cosine_of_opposite_vectors_is_negative_one() -> None:
    assert math.isclose(cosine_similarity((1.0, 0.0), (-1.0, 0.0)), -1.0, rel_tol=1e-9)


def test_cosine_length_mismatch_is_zero() -> None:
    # Defensive: mismatched dimensions score 0 instead of raising mid-retrieval.
    assert cosine_similarity((1.0, 2.0), (1.0, 2.0, 3.0)) == 0.0


def test_cosine_with_zero_magnitude_is_zero() -> None:
    assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_rank_orders_by_descending_score() -> None:
    query = (1.0, 0.0)
    candidates = [
        _candidate(1, (0.0, 1.0)),   # orthogonal -> 0.0
        _candidate(2, (1.0, 0.0)),   # identical  -> 1.0
        _candidate(3, (1.0, 1.0)),   # 45 degrees -> ~0.707
    ]
    ranked = rank_by_similarity(query, candidates, top_k=3)

    assert [chunk_id for chunk_id, _ in ranked] == [_uuid(2), _uuid(3), _uuid(1)]
    assert ranked[0][1] > ranked[1][1] > ranked[2][1]


def test_rank_caps_at_top_k() -> None:
    query = (1.0, 0.0)
    candidates = [_candidate(i, (1.0, 0.0)) for i in range(10)]

    ranked = rank_by_similarity(query, candidates, top_k=3)

    assert len(ranked) == 3


def test_rank_breaks_ties_deterministically_by_chunk_id() -> None:
    # All identical scores -> order must fall back to chunk_id.bytes, ascending,
    # so the same query always cites the same chunks in the same order.
    query = (1.0, 0.0)
    candidates = [
        _candidate(3, (1.0, 0.0)),
        _candidate(1, (1.0, 0.0)),
        _candidate(2, (1.0, 0.0)),
    ]
    ranked = rank_by_similarity(query, candidates, top_k=3)

    assert [chunk_id for chunk_id, _ in ranked] == [_uuid(1), _uuid(2), _uuid(3)]


def test_rank_with_non_positive_top_k_is_empty() -> None:
    query = (1.0, 0.0)
    candidates = [_candidate(1, (1.0, 0.0))]

    assert rank_by_similarity(query, candidates, top_k=0) == []
    assert rank_by_similarity(query, candidates, top_k=-1) == []


def test_rank_with_no_candidates_is_empty() -> None:
    assert rank_by_similarity((1.0, 0.0), [], top_k=5) == []
