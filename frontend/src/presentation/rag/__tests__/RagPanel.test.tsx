import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as ragApi from "@/infrastructure/api/ragApi";
import { RagPanel } from "@/presentation/rag/RagPanel";
import type { IndexStatus, IndexingResult, RagAnswer } from "@/domain/rag/types";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const REPO_ID = "22222222-2222-2222-2222-222222222222";

const STATUS_INDEXED: IndexStatus = {
  repositoryId: REPO_ID,
  indexed: true,
  chunkCount: 15,
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
  chunkCount: 15,
  embeddedCount: 12,
  reusedCount: 3,
  filesIndexed: 4,
  skippedFiles: 0,
  embeddingModel: "nomic-embed-text",
  indexedAt: "2026-08-28T18:05:00Z",
};

const GROUNDED_ANSWER: RagAnswer = {
  question: "How does search work?",
  answer: "Search uses binary search algorithm.",
  hasSufficientEvidence: true,
  sources: [
    {
      path: "search.py",
      startLine: 10,
      endLine: 30,
      score: 0.94,
      via: "vector",
      symbolQualifiedName: "binary_search",
      symbolKind: "function",
      snippet: "def binary_search(arr, target): return 42",
    },
  ],
  graphContext: [
    {
      qualifiedName: "linear_search",
      kind: "symbol",
      relationship: "calls",
      direction: "outgoing",
    },
  ],
  llmProvider: "ollama",
  llmModel: "qwen2.5-coder:3b",
  embeddingModel: "nomic-embed-text",
};

const INSUFFICIENT_ANSWER: RagAnswer = {
  question: "Where is rocket launch code?",
  answer: "I couldn't find code in this repository relevant enough to answer that question.",
  hasSufficientEvidence: false,
  sources: [],
  graphContext: [],
  llmProvider: "ollama",
  llmModel: "qwen2.5-coder:3b",
  embeddingModel: "nomic-embed-text",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(ragApi, "fetchIndexStatus").mockResolvedValue(STATUS_INDEXED);
  vi.spyOn(ragApi, "triggerIndex").mockResolvedValue(INDEXING_RESULT);
  vi.spyOn(ragApi, "askQuestion").mockResolvedValue(GROUNDED_ANSWER);
});

describe("RagPanel rendering", () => {
  it("renders nothing when enabled is false", () => {
    const { container } = render(
      <RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={false} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders index status and models when enabled", async () => {
    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });
    expect(screen.getByText("13 · Code intelligence (Ask Forge)")).toBeInTheDocument();
    expect(screen.getByText("nomic-embed-text")).toBeInTheDocument();
    expect(screen.getByText("qwen2.5-coder:3b")).toBeInTheDocument();
  });

  it("renders unindexed state and allows indexing", async () => {
    vi.spyOn(ragApi, "fetchIndexStatus").mockResolvedValue(STATUS_UNINDEXED);

    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Not indexed")).toBeInTheDocument();
    });

    const indexBtn = screen.getByRole("button", { name: "Index repository" });
    fireEvent.click(indexBtn);

    await waitFor(() => {
      expect(ragApi.triggerIndex).toHaveBeenCalledWith(PROJECT_ID, REPO_ID);
    });
  });

  it("submits a question and renders grounded answer and citations", async () => {
    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    fireEvent.change(input, { target: { value: "How does search work?" } });

    const askBtn = screen.getByRole("button", { name: "Ask Forge" });
    fireEvent.click(askBtn);

    await waitFor(() => {
      expect(screen.getByText("Search uses binary search algorithm.")).toBeInTheDocument();
    });

    expect(screen.getByText("search.py")).toBeInTheDocument();
    expect(screen.getByText("L10–L30")).toBeInTheDocument();
    expect(screen.getByText("94% match")).toBeInTheDocument();
    expect(screen.getByText("binary_search")).toBeInTheDocument();
    expect(screen.getByText("linear_search")).toBeInTheDocument();

    // Clicking citation card reveals snippet
    fireEvent.click(screen.getByText("search.py"));
    expect(screen.getByText("Retrieved code excerpt:")).toBeInTheDocument();
    expect(screen.getByText("def binary_search(arr, target): return 42")).toBeInTheDocument();
  });

  it("renders insufficient evidence state clearly", async () => {
    vi.spyOn(ragApi, "askQuestion").mockResolvedValue(INSUFFICIENT_ANSWER);

    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    fireEvent.change(input, { target: { value: "Where is rocket launch code?" } });

    const askBtn = screen.getByRole("button", { name: "Ask Forge" });
    fireEvent.click(askBtn);

    await waitFor(() => {
      expect(screen.getByText("Insufficient evidence")).toBeInTheDocument();
      expect(
        screen.getByText(
          "I couldn't find code in this repository relevant enough to answer that question.",
        ),
      ).toBeInTheDocument();
    });
  });

  it("starts with an empty query and Ask Forge button disabled", async () => {
    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText<HTMLInputElement>(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    expect(input.value).toBe("");

    const askBtn = screen.getByRole("button", { name: "Ask Forge" });
    expect(askBtn).toBeDisabled();
  });

  it("allows typing, editing, deleting, and replacing text freely", async () => {
    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText<HTMLInputElement>(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    const askBtn = screen.getByRole("button", { name: "Ask Forge" });

    // Type a custom question
    fireEvent.change(input, { target: { value: "Where is the FastAPI class defined?" } });
    expect(input.value).toBe("Where is the FastAPI class defined?");
    expect(askBtn).not.toBeDisabled();

    // Replace text (simulating select all + type)
    fireEvent.change(input, { target: { value: "How is dependency injection implemented?" } });
    expect(input.value).toBe("How is dependency injection implemented?");
    expect(askBtn).not.toBeDisabled();

    // Clear text (simulating backspace/delete all)
    fireEvent.change(input, { target: { value: "   " } });
    expect(input.value).toBe("   ");
    expect(askBtn).toBeDisabled();

    // Re-type and submit
    fireEvent.change(input, { target: { value: "Final custom question" } });
    expect(input.value).toBe("Final custom question");
    expect(askBtn).not.toBeDisabled();

    fireEvent.click(askBtn);
    await waitFor(() => {
      expect(ragApi.askQuestion).toHaveBeenCalledWith(PROJECT_ID, REPO_ID, "Final custom question");
    });
  });

  it("seeds initialQuestion if provided, and allows editing without reverting", async () => {
    render(
      <RagPanel
        projectId={PROJECT_ID}
        repositoryId={REPO_ID}
        enabled={true}
        initialQuestion="What are the upstream callers and downstream dependencies of FastAPI?"
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText<HTMLInputElement>(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    expect(input.value).toBe(
      "What are the upstream callers and downstream dependencies of FastAPI?",
    );

    // Edit the text
    fireEvent.change(input, {
      target: { value: "Where is the route handler for /items defined?" },
    });
    // Ensure it was NOT reset back to initialQuestion
    expect(input.value).toBe("Where is the route handler for /items defined?");

    const askBtn = screen.getByRole("button", { name: "Ask Forge" });
    fireEvent.click(askBtn);

    await waitFor(() => {
      expect(ragApi.askQuestion).toHaveBeenCalledWith(
        PROJECT_ID,
        REPO_ID,
        "Where is the route handler for /items defined?",
      );
    });
  });

  it("populates field on suggested question click and allows user to edit before submitting", async () => {
    render(<RagPanel projectId={PROJECT_ID} repositoryId={REPO_ID} enabled={true} />);

    await waitFor(() => {
      expect(screen.getByText("Indexed (15 chunks)")).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText<HTMLInputElement>(
      "Ask about functions, classes, dependencies, or workflows…",
    );
    const chipBtn = screen.getByRole("button", { name: "How does authentication work?" });

    // Click chip
    fireEvent.click(chipBtn);
    expect(input.value).toBe("How does authentication work?");

    // It should NOT have submitted yet
    expect(ragApi.askQuestion).not.toHaveBeenCalled();

    // User edits the populated suggestion
    fireEvent.change(input, {
      target: { value: "How does authentication work with OAuth2?" },
    });
    expect(input.value).toBe("How does authentication work with OAuth2?");

    // User submits the final edited query
    const askBtn = screen.getByRole("button", { name: "Ask Forge" });
    fireEvent.click(askBtn);

    await waitFor(() => {
      expect(ragApi.askQuestion).toHaveBeenCalledWith(
        PROJECT_ID,
        REPO_ID,
        "How does authentication work with OAuth2?",
      );
    });
  });
});

