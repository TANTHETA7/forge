import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/infrastructure/api/client";
import { askQuestion, fetchIndexStatus, triggerIndex } from "@/infrastructure/api/ragApi";

const PROJECT = "11111111-1111-1111-1111-111111111111";
const REPO = "22222222-2222-2222-2222-222222222222";
const BASE = `/projects/${PROJECT}/repositories/${REPO}`;

let apiGet: ReturnType<typeof vi.spyOn>;
let apiPost: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.restoreAllMocks();
  apiGet = vi.spyOn(client, "apiGet");
  apiPost = vi.spyOn(client, "apiPost");
});

describe("fetchIndexStatus", () => {
  it("requests /rag/status and maps wire fields to domain model", async () => {
    apiGet.mockResolvedValue({
      repository_id: REPO,
      indexed: true,
      chunk_count: 42,
      embedding_model: "nomic-embed-text",
      last_indexed_at: "2026-08-28T18:00:00Z",
    });

    const status = await fetchIndexStatus(PROJECT, REPO);

    expect(apiGet).toHaveBeenCalledWith(`${BASE}/rag/status`);
    expect(status).toEqual({
      repositoryId: REPO,
      indexed: true,
      chunkCount: 42,
      embeddingModel: "nomic-embed-text",
      lastIndexedAt: "2026-08-28T18:00:00Z",
    });
  });
});

describe("triggerIndex", () => {
  it("posts to /rag/index and maps response", async () => {
    apiPost.mockResolvedValue({
      repository_id: REPO,
      chunk_count: 10,
      embedded_count: 8,
      reused_count: 2,
      files_indexed: 5,
      skipped_files: 0,
      embedding_model: "nomic-embed-text",
      indexed_at: "2026-08-28T18:05:00Z",
    });

    const result = await triggerIndex(PROJECT, REPO);

    expect(apiPost).toHaveBeenCalledWith(`${BASE}/rag/index`);
    expect(result).toEqual({
      repositoryId: REPO,
      chunkCount: 10,
      embeddedCount: 8,
      reusedCount: 2,
      filesIndexed: 5,
      skippedFiles: 0,
      embeddingModel: "nomic-embed-text",
      indexedAt: "2026-08-28T18:05:00Z",
    });
  });
});

describe("askQuestion", () => {
  it("posts question to /rag/ask and maps grounded answer with sources and graph context", async () => {
    apiPost.mockResolvedValue({
      question: "How does binary search work?",
      answer: "Binary search divides the search space in half.",
      has_sufficient_evidence: true,
      sources: [
        {
          path: "search.py",
          start_line: 10,
          end_line: 25,
          score: 0.89,
          via: "vector",
          symbol_qualified_name: "binary_search",
          symbol_kind: "function",
        },
      ],
      graph_context: [
        {
          qualified_name: "linear_search",
          kind: "symbol",
          relationship: "calls",
          direction: "outgoing",
        },
      ],
      llm_provider: "ollama",
      llm_model: "qwen2.5-coder:3b",
      embedding_model: "nomic-embed-text",
    });

    const answer = await askQuestion(PROJECT, REPO, "How does binary search work?");

    expect(apiPost).toHaveBeenCalledWith(`${BASE}/rag/ask`, {
      question: "How does binary search work?",
    });
    expect(answer.hasSufficientEvidence).toBe(true);
    expect(answer.sources).toHaveLength(1);
    expect(answer.sources[0]).toEqual({
      path: "search.py",
      startLine: 10,
      endLine: 25,
      score: 0.89,
      via: "vector",
      symbolQualifiedName: "binary_search",
      symbolKind: "function",
    });
    expect(answer.graphContext).toHaveLength(1);
    expect(answer.graphContext[0]).toEqual({
      qualifiedName: "linear_search",
      kind: "symbol",
      relationship: "calls",
      direction: "outgoing",
    });
  });
});

