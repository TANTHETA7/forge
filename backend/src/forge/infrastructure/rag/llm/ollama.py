"""Ollama LLM provider (Phase 7).

Purpose:       Generate a grounded answer by calling a local Ollama server's
                `/api/chat` endpoint with the code-intelligence model (default
                `qwen2.5-coder:3b`).
Responsibility: One `LlmProvider` implementation. Request shaping (system/user
                messages, deterministic-leaning options) and response validation
                only. It receives an already-assembled, already-bounded prompt —
                it never selects sources, never fetches anything, and its output
                never determines the citations attached to an answer.
Depends on:    infrastructure/rag/ollama_client.py, domain/errors.py.
Depended on by: infrastructure/rag/dependencies.py.

`stream=False`: the answer is consumed whole by the API layer, so a single
response is simpler and lets `OllamaClient` validate one JSON object. Temperature
is kept low (config default 0.1) because this is grounded Q&A over supplied code,
not open-ended generation.
"""

from __future__ import annotations

from forge.domain.errors import RagProviderError
from forge.infrastructure.rag.ollama_client import OllamaClient

_CHAT_PATH = "/api/chat"


class OllamaLlmProvider:
    """An `LlmProvider` backed by a local Ollama chat model."""

    def __init__(
        self,
        *,
        client: OllamaClient,
        model: str,
        temperature: float,
        num_ctx: int,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._num_ctx = num_ctx

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, *, system: str, prompt: str) -> str:
        """Return the model's completion for `prompt` under `system`. Raises
        `RagProviderError` on transport failure or a malformed/empty response."""
        data = await self._client.post_json(
            _CHAT_PATH,
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": self._temperature,
                    "num_ctx": self._num_ctx,
                },
            },
        )
        message = data.get("message")
        if not isinstance(message, dict):
            raise RagProviderError(
                f"Ollama {_CHAT_PATH} returned no message object (model {self._model!r})"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RagProviderError(
                f"Ollama {_CHAT_PATH} returned an empty completion (model {self._model!r})"
            )
        return content.strip()
