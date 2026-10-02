"""Ollama HTTP client helper (Phase 7).

Purpose:       One place that talks HTTP to a local Ollama server and turns every
                transport/protocol failure into a `RagProviderError`, so neither
                the embedding provider nor the LLM provider ever lets a raw
                `httpx` exception cross out of infrastructure.
Responsibility: A single `post_json` call — POST a JSON body, validate the
                status, parse the JSON object. No knowledge of embeddings or
                chat specifically; the callers own their request/response shapes.
Depends on:    httpx, domain/errors.py.
Depended on by: infrastructure/rag/embeddings/ollama.py,
                infrastructure/rag/llm/ollama.py.

A fresh `httpx.AsyncClient` is opened per call. Against a localhost Ollama that
overhead is immaterial, and it keeps this helper free of any client-lifecycle
state to leak across the per-request DI scope — correctness over a micro-
optimization that isn't needed here.
"""

from __future__ import annotations

from typing import Any

import httpx

from forge.domain.errors import RagProviderError

# How much of an error-response body to echo in a raised message — enough to
# surface Ollama's own "model not found"-style detail, bounded so a large HTML
# error page can't bloat the exception.
_ERROR_BODY_LIMIT = 500


class OllamaClient:
    """Thin async JSON-over-HTTP client for a local Ollama server."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST `payload` as JSON to `path` and return the parsed JSON object.

        Raises `RagProviderError` if the server is unreachable, times out,
        returns a non-2xx status (missing model, bad request), or returns a body
        that isn't a JSON object.
        """
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise RagProviderError(f"Ollama request to {path} failed: {exc}") from exc

        if response.status_code >= 400:
            raise RagProviderError(
                f"Ollama {path} returned HTTP {response.status_code}: "
                f"{response.text[:_ERROR_BODY_LIMIT]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RagProviderError(
                f"Ollama {path} returned a non-JSON response"
            ) from exc

        if not isinstance(data, dict):
            raise RagProviderError(f"Ollama {path} returned {type(data).__name__}, expected object")
        return data
