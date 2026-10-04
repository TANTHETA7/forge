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
from dataclasses import dataclass
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


# --- Hybrid Retrieval & Rank Fusion (RAG V2 / Phase 1) -----------------------

STOP_WORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "couldn",
    "did", "didn", "do", "does", "doesn", "doing", "don", "down", "during", "each",
    "few", "for", "from", "further", "had", "hadn", "has", "hasn", "have", "haven",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "isn", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "shan", "she", "should", "shouldn", "so",
    "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn", "we", "were", "weren", "what",
    "when", "where", "which", "while", "who", "whom", "why", "with", "won",
    "would", "wouldn", "you", "your", "yours", "yourself", "yourselves",
    # Common conversational question fillers
    "explain", "describe", "find", "show", "tell", "give", "code", "used", "work",
    "works", "use", "uses", "using", "implement", "implements", "implementation",
})


def find_symbol_candidates(query: str) -> list[str]:
    """Extract candidate symbol/function/class/module names from `query`.

    Prioritizes specific programming identifiers (quoted, snake_case, PascalCase,
    dotted names) before general word tokens. Case is preserved for exact lookup.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        token = raw.strip("`'\",:;()[]{}*").strip()
        if not token or token in seen or token.lower() in STOP_WORDS or len(token) < 2:
            return
        seen.add(token)
        candidates.append(token)

    import re

    # 1. Backticked or explicitly quoted tokens: `symbol`, 'symbol', "symbol"
    for match in re.findall(r"[`'\"]([A-Za-z_][A-Za-z0-9_.]*)[`'\"]", query):
        _add(match)

    # 2. Dotted identifiers: e.g. `auth.login.authenticate`, `shapes.Circle`
    for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b", query):
        _add(match)

    # 3. snake_case identifiers containing underscore: e.g. `create_repository`
    for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b", query):
        _add(match)

    # 4. PascalCase / CamelCase identifiers: e.g. `GraphProjectionService`, `Circle`
    for match in re.findall(r"\b[A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*\b", query):
        _add(match)

    # 5. Any remaining identifier-like word token
    for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", query):
        _add(match)

    return candidates


def extract_lexical_terms(query: str) -> list[str]:
    """Extract clean, significant search keywords from `query` for full-text and
    lexical matching. Preserves query order and strips stop words.
    """
    import re

    tokens = re.findall(r"\b[A-Za-z0-9_]+\b", query)
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        clean = token.strip("_").lower()
        if not clean or clean in seen or clean in STOP_WORDS or len(clean) < 2:
            continue
        seen.add(clean)
        terms.append(clean)
    return terms


@dataclass(frozen=True, slots=True)
class HybridRetrievalDebug:
    """Internal candidate count metrics across retrieval branches for observability."""

    semantic_count: int
    lexical_count: int
    exact_symbol_count: int
    merged_count: int
    final_count: int


def fuse_hybrid_candidates(
    *,
    semantic_ranked: Sequence[tuple[UUID, float]],
    lexical_chunk_ids: Sequence[UUID],
    symbol_chunk_ids: Sequence[UUID],
    top_k: int,
    rrf_k: int = 60,
    weight_semantic: float = 1.0,
    weight_lexical: float = 1.0,
    weight_symbol: float = 2.0,
) -> tuple[list[tuple[UUID, str, float]], HybridRetrievalDebug]:
    """Combine and rank candidate pools via Weighted Reciprocal Rank Fusion (RRF).

    Why Weighted RRF:
      Embedding cosine similarities ([-1, 1]), full-text rank scores ([0, inf)),
      and boolean exact symbol matches live in incompatible coordinate spaces.
      Reciprocal Rank Fusion (Cormack et al., 2009) normalizes via 1-based ranks
      rather than uncalibrated raw scores, guaranteeing scale invariance and
      deterministic combination. Weights bias toward exact symbol hits when
      present while allowing semantic and lexical signals to reinforce.

    Attributes:
      semantic_ranked: (chunk_id, cosine_score) pairs in descending order.
      lexical_chunk_ids: chunk_ids matching keyword/full-text search.
      symbol_chunk_ids: chunk_ids matching extracted symbol names.
      top_k: max candidates to keep.
      rrf_k: smoothing constant (standard default 60).
      weight_symbol: strong priority weight for exact symbol matches (default 2.0).

    Returns:
      A list of `(chunk_id, via, score)` tuples capped at `top_k`, and debug metrics.
      Ties break deterministically on `chunk_id.bytes`.
    """
    if top_k <= 0:
        debug = HybridRetrievalDebug(
            semantic_count=len(semantic_ranked),
            lexical_count=len(lexical_chunk_ids),
            exact_symbol_count=len(symbol_chunk_ids),
            merged_count=0,
            final_count=0,
        )
        return [], debug

    semantic_rank = {cid: idx + 1 for idx, (cid, _) in enumerate(semantic_ranked)}
    lexical_rank = {cid: idx + 1 for idx, cid in enumerate(lexical_chunk_ids)}
    symbol_rank = {cid: idx + 1 for idx, cid in enumerate(symbol_chunk_ids)}

    all_chunk_ids = set(semantic_rank.keys()) | set(lexical_rank.keys()) | set(symbol_rank.keys())

    fused_scores: dict[UUID, float] = {}
    candidate_via: dict[UUID, str] = {}

    for cid in all_chunk_ids:
        score = 0.0
        if cid in symbol_rank:
            score += weight_symbol / (rrf_k + symbol_rank[cid])
        if cid in lexical_rank:
            score += weight_lexical / (rrf_k + lexical_rank[cid])
        if cid in semantic_rank:
            score += weight_semantic / (rrf_k + semantic_rank[cid])
        fused_scores[cid] = score

        # Provenance: preserve "vector" if found semantically (matches existing contracts);
        # otherwise surface "symbol" or "lexical".
        if cid in semantic_rank:
            candidate_via[cid] = "vector"
        elif cid in symbol_rank:
            candidate_via[cid] = "symbol"
        else:
            candidate_via[cid] = "lexical"

    sorted_candidates = [
        (cid, candidate_via[cid], fused_scores[cid])
        for cid in all_chunk_ids
    ]
    sorted_candidates.sort(key=lambda item: (-item[2], item[0].bytes))
    final = sorted_candidates[:top_k]

    debug = HybridRetrievalDebug(
        semantic_count=len(semantic_ranked),
        lexical_count=len(lexical_chunk_ids),
        exact_symbol_count=len(symbol_chunk_ids),
        merged_count=len(all_chunk_ids),
        final_count=len(final),
    )
    return final, debug
