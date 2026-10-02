"""Deterministic extractive LLM provider (Phase 7).

Purpose:       Produce a grounded-looking answer without any model server, so the
                RAG pipeline can be unit-tested end to end offline. NOT a
                production path — it does no reasoning; it extracts.
Responsibility: One `LlmProvider` implementation. Given the assembled prompt (the
                question plus the already-retrieved code context), it returns a
                deterministic extract of that context. Because Forge's grounding
                guarantee builds citations from the *retrieved chunks*, never from
                model output (see application/rag/ask_service.py), a simple
                extractive double exercises the whole pipeline — retrieval,
                threshold, grounding, source assembly — faithfully; only the prose
                differs from a real model's.
Depends on:    stdlib only.
Depended on by: infrastructure/rag/dependencies.py (only when
                `rag_llm_provider="extractive"`).

Deliberately decoupled from the exact prompt format: it extracts the first few
substantive lines of whatever prompt it is handed, so it keeps working if prompt
assembly changes. Deterministic by construction (no clock, no randomness, no
network) — the same prompt always yields the same answer.
"""

from __future__ import annotations

_MODEL_NAME = "extractive"
# How many substantive lines to echo back as the "answer".
_MAX_LINES = 4
# A line shorter than this (after stripping) is treated as structural noise
# (blank lines, fences, single braces) and skipped.
_MIN_LINE_CHARS = 8


class ExtractiveLlmProvider:
    """An offline, deterministic `LlmProvider` that extracts from its prompt."""

    @property
    def model_name(self) -> str:
        return _MODEL_NAME

    async def generate(self, *, system: str, prompt: str) -> str:
        """Return a deterministic extract of the first substantive lines of
        `prompt`, or a fixed fallback if it contains none."""
        substantive: list[str] = []
        for raw_line in prompt.splitlines():
            line = raw_line.strip()
            if len(line) >= _MIN_LINE_CHARS:
                substantive.append(line)
            if len(substantive) >= _MAX_LINES:
                break
        if not substantive:
            return "No answer could be extracted from the provided context."
        return "Based on the retrieved code:\n" + "\n".join(substantive)
