"""Grounded prompt assembly (Phase 7).

Purpose:       Build the system instruction and the user prompt for grounded code
                Q&A — turning a question plus the repository-scoped retrieved
                chunks (and bounded graph context) into the exact text the LLM
                sees.
Responsibility: Pure string assembly with a hard character budget. No IO, no
                model calls, no source selection beyond ordering/truncating what
                it is given. Kept in the domain (not application) so both the
                application service and the offline test double share one
                definition of the prompt contract.

Two invariants this module enforces:
  * Bounded context — chunks are added in score order until `max_context_chars`
    is reached; the whole repository is never dumped into a prompt. The single
    top chunk is always included (truncated if it alone exceeds the budget), so
    there is always *some* grounding to answer from.
  * Explicit insufficiency — the system prompt instructs the model to reply with
    exactly `INSUFFICIENT_EVIDENCE_MARKER` when the supplied context does not
    contain the answer, rather than guessing. The application layer treats that
    marker as "no sufficient evidence" (see application/rag/ask_service.py).

Citations are NOT produced here and are NOT parsed from the model's reply — the
application builds them from the retrieved chunks' real metadata. The numbered
`[n]` labels below are only to let the model *refer* to a source in prose; they
never become the citation of record.

Depends on:    domain/rag/entities.py.
Depended on by: application/rag/ask_service.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from forge.domain.rag.entities import GraphContextItem, RetrievedChunk

# The exact token the model must emit (alone) when the context can't answer the
# question. Checked by the application layer — keep in sync there.
INSUFFICIENT_EVIDENCE_MARKER = "INSUFFICIENT_EVIDENCE"

SYSTEM_PROMPT = (
    "You are Forge's code intelligence assistant. You answer questions about a "
    "single software repository using ONLY the code excerpts provided in the "
    "user's message.\n\n"
    "Rules:\n"
    "- Ground every statement in the provided excerpts. Do not use outside "
    "knowledge about libraries or code that is not shown.\n"
    "- Do not invent file names, functions, classes, or behavior that the "
    "excerpts do not show.\n"
    "- When you refer to code, name the file and symbol it comes from.\n"
    "- Be concise and technical. Prefer specifics from the excerpts over general "
    "explanation.\n"
    f"- If the excerpts do not contain enough information to answer, reply with "
    f"exactly {INSUFFICIENT_EVIDENCE_MARKER} and nothing else."
)


def build_user_prompt(
    *,
    question: str,
    retrieved: Sequence[RetrievedChunk],
    graph_context: Sequence[GraphContextItem],
    max_context_chars: int,
) -> str:
    """Assemble the user prompt: the question, a bounded set of numbered code
    excerpts, and any related symbols from graph expansion.

    Args:
        question: The user's question, verbatim.
        retrieved: Retrieved chunks, already ordered best-first. Added until the
            character budget is reached; the first is always included.
        graph_context: Related symbols surfaced by bounded graph expansion, shown
            as structural hints (names only — their code, if retrieved, already
            appears among `retrieved`).
        max_context_chars: Hard ceiling on the assembled code-excerpt characters.

    Returns:
        The full user-message text.
    """
    blocks: list[str] = []
    used = 0
    for index, item in enumerate(retrieved, start=1):
        block = _format_chunk(index, item)
        # Always include the first block (truncated if it alone busts the budget)
        # so there is grounding to answer from; stop once the budget is reached.
        if blocks and used + len(block) > max_context_chars:
            break
        if not blocks and len(block) > max_context_chars:
            block = block[:max_context_chars]
        blocks.append(block)
        used += len(block)

    sections = [f"Question:\n{question.strip()}", "", "Code excerpts:", *blocks]

    if graph_context:
        related = "\n".join(
            f"- {item.qualified_name} ({item.kind}) — {item.relationship} "
            f"[{item.direction}]"
            for item in graph_context
        )
        sections.extend(["", "Related symbols (from the dependency graph):", related])

    sections.extend(
        [
            "",
            "Answer the question using only the excerpts above. If they are "
            f"insufficient, reply with exactly {INSUFFICIENT_EVIDENCE_MARKER}.",
        ]
    )
    return "\n".join(sections)


def _format_chunk(index: int, item: RetrievedChunk) -> str:
    """Render one retrieved chunk as a labeled, fenced excerpt."""
    chunk = item.chunk
    location = f"{chunk.path}:{chunk.start_line}-{chunk.end_line}"
    if chunk.symbol_qualified_name:
        location += f" ({chunk.symbol_kind} {chunk.symbol_qualified_name})"
    return f"[{index}] {location}\n```{chunk.language}\n{chunk.content}\n```"
