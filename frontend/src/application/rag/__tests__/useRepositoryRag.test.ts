import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRepositoryRag } from "@/application/rag/useRepositoryRag";
import * as ragApi from "@/infrastructure/api/ragApi";
import type { IndexStatus, IndexingResult, RagAnswer } from "@/domain/rag/types";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const REPO_ID = "22222222-2222-2222-2222-222222222222";

const STATUS_INDEXED: IndexStatus = {
  repositoryId: REPO_ID,
  indexed: true,
  chunkCount: 25,
  embeddingModel: "nomic-embed-text",
  lastIndexedAt: "2026-08-28T18:00:00Z",
};

const STATUS_UNINDEXED: IndexStatus = {
  repositoryId: REPO_ID,
  indexed: false,
  chunkCount: 0,
  embeddingModel: null,
  lastIndexedAt: null,
};

const INDEXING_RESULT: IndexingResult = {
  repositoryId: REPO_ID,
  chunkCount: 25,
  embeddedCount: 20,
  reusedCount: 5,
  filesIndexed: 8,
  skippedFiles: 0,
  embeddingModel: "nomic-embed-text",
  indexedAt: "2026-08-28T18:05:00Z",
};

const ANSWER: RagAnswer = {
  question: "How is graph projected?",
  answer: "It projects dependency edges into Neo4j nodes and relationships.",
  hasSufficientEvidence: true,
  sources: [
    {
      path: "projection.py",
      startLine: 1,
      endLine: 20,
      score: 0.92,
      via: "vector",
      symbolQualifiedName: "project_graph",
      symbolKind: "function",
    },
  ],
  graphContext: [],
  llmProvider: "ollama",
  llmModel: "qwen2.5-coder:3b",
  embeddingModel: "nomic-embed-text",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(ragApi, "fetchIndexStatus").mockResolvedValue(STATUS_INDEXED);
  vi.spyOn(ragApi, "triggerIndex").mockResolvedValue(INDEXING_RESULT);
  vi.spyOn(ragApi, "askQuestion").mockResolvedValue(ANSWER);
});

describe("useRepositoryRag status loading", () => {
  it("does not fetch status when enabled is false", () => {
    const { result } = renderHook(() => useRepositoryRag(PROJECT_ID, REPO_ID, false));

    expect(result.current.status.isLoading).toBe(false);
    expect(result.current.status.data).toBeNull();
    expect(ragApi.fetchIndexStatus).not.toHaveBeenCalled();
  });

  it("fetches status when enabled", async () => {
    const { result } = renderHook(() => useRepositoryRag(PROJECT_ID, REPO_ID, true));

    await waitFor(() => {
      expect(result.current.status.data).toEqual(STATUS_INDEXED);
    });
    expect(result.current.isIndexed).toBe(true);
  });
});

describe("useRepositoryRag indexing", () => {
  it("triggers indexing and reloads status", async () => {
    const fetchStatusSpy = vi
      .spyOn(ragApi, "fetchIndexStatus")
      .mockResolvedValueOnce(STATUS_UNINDEXED)
      .mockResolvedValueOnce(STATUS_INDEXED);

    const { result } = renderHook(() => useRepositoryRag(PROJECT_ID, REPO_ID, true));

    await waitFor(() => {
      expect(result.current.status.data).toEqual(STATUS_UNINDEXED);
    });
    expect(result.current.isIndexed).toBe(false);

    await act(async () => {
      await result.current.handleIndex();
    });

    expect(ragApi.triggerIndex).toHaveBeenCalledWith(PROJECT_ID, REPO_ID);
    expect(result.current.indexing.data).toEqual(INDEXING_RESULT);

    await waitFor(() => {
      expect(fetchStatusSpy).toHaveBeenCalledTimes(2);
    });
  });
});

describe("useRepositoryRag asking questions", () => {
  it("submits question and receives answer", async () => {
    const { result } = renderHook(() => useRepositoryRag(PROJECT_ID, REPO_ID, true));

    await waitFor(() => {
      expect(result.current.isIndexed).toBe(true);
    });

    act(() => {
      result.current.setQuestion("How is graph projected?");
    });
    expect(result.current.canAsk).toBe(true);

    await act(async () => {
      await result.current.handleAsk();
    });

    expect(ragApi.askQuestion).toHaveBeenCalledWith(
      PROJECT_ID,
      REPO_ID,
      "How is graph projected?",
    );
    expect(result.current.ask.data).toEqual(ANSWER);
  });

  it("selects and deselects sources", async () => {
    const { result } = renderHook(() => useRepositoryRag(PROJECT_ID, REPO_ID, true));

    await waitFor(() => {
      expect(result.current.status.data).toEqual(STATUS_INDEXED);
    });

    expect(result.current.selectedSource).toBeNull();
    act(() => {
      result.current.selectSource(ANSWER.sources[0]);
    });
    expect(result.current.selectedSource).toEqual(ANSWER.sources[0]);
  });
});
