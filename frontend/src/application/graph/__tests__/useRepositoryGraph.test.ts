import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  GRAPH_NODE_LIMIT,
  GRAPH_RELATIONSHIP_LIMIT,
  NEIGHBOR_LIMIT,
  useRepositoryGraph,
} from "@/application/graph/useRepositoryGraph";
import * as graphApi from "@/infrastructure/api/graphApi";
import type {
  FileGraphNode,
  GraphNeighbor,
  GraphNode,
  GraphRelationship,
  GraphStatistics,
  RepositoryGraphNode,
  SymbolGraphNode,
} from "@/domain/graph/types";

const PROJECT = "11111111-1111-1111-1111-111111111111";
const REPO = "22222222-2222-2222-2222-222222222222";

const repoNode: RepositoryGraphNode = {
  id: "n-repo",
  kind: "repository",
  repositoryId: REPO,
  displayName: "graphrepo",
  projectId: PROJECT,
  projectedAt: "2026-08-21T17:54:26Z",
};

const fileNode: FileGraphNode = {
  id: "n-file",
  kind: "file",
  repositoryId: REPO,
  path: "pkg/dog.py",
  language: "python",
  hasSyntaxErrors: false,
};

const symbolNode: SymbolGraphNode = {
  id: "n-sym",
  kind: "symbol",
  repositoryId: REPO,
  name: "bark",
  qualifiedName: "pkg.dog.bark",
  symbolKind: "function",
  fileId: "f1",
  startLine: 5,
  endLine: 6,
};

const NODES: GraphNode[] = [repoNode, fileNode, symbolNode];

const rel = (sourceId: string, targetId: string, kind: string): GraphRelationship => ({
  id: `${sourceId}->${targetId}:${kind}`,
  sourceId,
  targetId,
  kind,
  dependencyEdgeId: null,
});

const RELATIONSHIPS = [rel("n-repo", "n-file", "contains"), rel("n-file", "n-sym", "defines")];

const STATS: GraphStatistics = {
  repositoryId: REPO,
  totalNodes: 3,
  totalFiles: 1,
  totalSymbols: 1,
  totalRelationships: 2,
  relationshipsByKind: [{ kind: "contains", count: 1 }],
  highestInDegree: [{ node: fileNode, degree: 2 }],
  highestOutDegree: [{ node: repoNode, degree: 1 }],
  projectedAt: "2026-08-21T17:54:26Z",
  freshness: "fresh",
  computedAt: "2026-08-21T17:54:37Z",
};

const NEIGHBORS: GraphNeighbor[] = [
  { node: repoNode, relationshipKind: "contains", direction: "incoming" },
  { node: symbolNode, relationshipKind: "defines", direction: "outgoing" },
];

function render(enabled = true) {
  return renderHook(() => useRepositoryGraph(PROJECT, REPO, enabled));
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(graphApi, "fetchGraphNodes").mockResolvedValue(NODES);
  vi.spyOn(graphApi, "fetchGraphRelationships").mockResolvedValue(RELATIONSHIPS);
  vi.spyOn(graphApi, "fetchGraphStatistics").mockResolvedValue(STATS);
  vi.spyOn(graphApi, "fetchGraphNeighbors").mockResolvedValue(NEIGHBORS);
});

describe("useRepositoryGraph loading", () => {
  it("reports loading before the graph arrives", () => {
    const { result } = render();
    expect(result.current.isLoading).toBe(true);
    expect(result.current.graph.nodes).toEqual([]);
  });

  it("opens with exactly three requests and no neighbor request", async () => {
    const { result } = render();

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(graphApi.fetchGraphNodes).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchGraphRelationships).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchGraphStatistics).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchGraphNeighbors).not.toHaveBeenCalled();
  });

  it("bounds the initial load explicitly", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(graphApi.fetchGraphNodes).toHaveBeenCalledWith(PROJECT, REPO, {
      limit: GRAPH_NODE_LIMIT,
      offset: 0,
    });
    expect(graphApi.fetchGraphRelationships).toHaveBeenCalledWith(PROJECT, REPO, {
      limit: GRAPH_RELATIONSHIP_LIMIT,
      offset: 0,
    });
  });

  it("does not re-fetch on re-render", async () => {
    const { result, rerender } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    rerender();
    rerender();

    expect(graphApi.fetchGraphNodes).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchGraphRelationships).toHaveBeenCalledTimes(1);
  });
});

describe("useRepositoryGraph locked state", () => {
  it("issues no requests until projection has succeeded", async () => {
    const { result } = render(false);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(graphApi.fetchGraphNodes).not.toHaveBeenCalled();
    expect(graphApi.fetchGraphRelationships).not.toHaveBeenCalled();
    expect(graphApi.fetchGraphStatistics).not.toHaveBeenCalled();
    expect(result.current.graph.nodes).toEqual([]);
  });
});

describe("useRepositoryGraph empty and error states", () => {
  it("reports an empty projection distinctly from loading", async () => {
    vi.spyOn(graphApi, "fetchGraphNodes").mockResolvedValue([]);
    vi.spyOn(graphApi, "fetchGraphRelationships").mockResolvedValue([]);
    const { result } = render();

    await waitFor(() => expect(result.current.isEmpty).toBe(true));
    expect(result.current.error).toBeNull();
  });

  it("surfaces the backend's error message", async () => {
    vi.spyOn(graphApi, "fetchGraphNodes").mockRejectedValue(new Error("graph is stale"));
    const { result } = render();

    await waitFor(() => expect(result.current.error).toBe("graph is stale"));
    expect(result.current.isEmpty).toBe(false);
  });
});

describe("useRepositoryGraph relationship joining", () => {
  it("keeps only relationships whose endpoints are both loaded, and counts the rest", async () => {
    vi.spyOn(graphApi, "fetchGraphRelationships").mockResolvedValue([
      ...RELATIONSHIPS,
      rel("n-file", "n-outside", "imports"),
      rel("n-missing", "n-sym", "calls"),
    ]);
    const { result } = render();

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.graph.relationships.map((r) => r.id)).toEqual([
      "n-repo->n-file:contains",
      "n-file->n-sym:defines",
    ]);
    expect(result.current.graph.omittedRelationshipCount).toBe(2);
  });

  it("flags a bounded view when the projection is larger than the loaded page", async () => {
    vi.spyOn(graphApi, "fetchGraphStatistics").mockResolvedValue({ ...STATS, totalNodes: 5000 });
    const { result } = render();

    await waitFor(() => expect(result.current.isTruncated).toBe(true));
  });

  it("does not flag truncation when everything is loaded", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await waitFor(() => expect(result.current.statistics.data).not.toBeNull());

    expect(result.current.isTruncated).toBe(false);
  });
});

describe("useRepositoryGraph selection and neighbors", () => {
  it("fetches neighbors only once a node is selected", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(graphApi.fetchGraphNeighbors).not.toHaveBeenCalled();

    act(() => result.current.selectNode(fileNode));

    await waitFor(() => expect(result.current.neighbors.data).toEqual(NEIGHBORS));
    expect(graphApi.fetchGraphNeighbors).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchGraphNeighbors).toHaveBeenCalledWith(
      PROJECT,
      REPO,
      "n-file",
      NEIGHBOR_LIMIT,
    );
  });

  it("issues one neighbor request per selection regardless of graph size", async () => {
    const many: GraphNode[] = Array.from({ length: 120 }, (_, i) => ({
      ...symbolNode,
      id: `s${i}`,
      name: `sym${i}`,
    }));
    vi.spyOn(graphApi, "fetchGraphNodes").mockResolvedValue(many);
    const { result } = render();
    await waitFor(() => expect(result.current.graph.nodes).toHaveLength(120));

    // 120 nodes rendered, still nothing fetched per node.
    expect(graphApi.fetchGraphNeighbors).not.toHaveBeenCalled();

    act(() => result.current.selectNode(many[7]));
    await waitFor(() => expect(result.current.neighbors.isLoading).toBe(false));

    expect(graphApi.fetchGraphNeighbors).toHaveBeenCalledTimes(1);
  });

  it("selecting a neighbor makes it the selected node and fetches its neighbors", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.selectNode(fileNode));
    await waitFor(() => expect(result.current.neighbors.data).not.toBeNull());

    // Neighbors carry full nodes, so a neighbor outside the loaded page still selects.
    act(() => result.current.selectNode(repoNode));
    await waitFor(() => expect(result.current.selectedNode?.id).toBe("n-repo"));

    expect(graphApi.fetchGraphNeighbors).toHaveBeenCalledTimes(2);
    expect(graphApi.fetchGraphNeighbors).toHaveBeenLastCalledWith(
      PROJECT,
      REPO,
      "n-repo",
      NEIGHBOR_LIMIT,
    );
  });

  it("reports a node with no neighbors as empty rather than loading", async () => {
    vi.spyOn(graphApi, "fetchGraphNeighbors").mockResolvedValue([]);
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.selectNode(symbolNode));

    await waitFor(() => expect(result.current.neighbors.data).toEqual([]));
    expect(result.current.neighbors.isLoading).toBe(false);
    expect(result.current.neighbors.error).toBeNull();
  });

  it("surfaces a neighbor request failure without losing the graph", async () => {
    vi.spyOn(graphApi, "fetchGraphNeighbors").mockRejectedValue(new Error("neighbors failed"));
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.selectNode(fileNode));

    await waitFor(() => expect(result.current.neighbors.error).toBe("neighbors failed"));
    expect(result.current.graph.nodes).toHaveLength(3);
    expect(result.current.error).toBeNull();
  });

  it("clears the selection without fetching again", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.selectNode(fileNode));
    await waitFor(() => expect(result.current.neighbors.data).not.toBeNull());

    act(() => result.current.selectNode(null));

    await waitFor(() => expect(result.current.selectedNode).toBeNull());
    expect(result.current.neighbors.data).toBeNull();
    expect(graphApi.fetchGraphNeighbors).toHaveBeenCalledTimes(1);
  });
});
