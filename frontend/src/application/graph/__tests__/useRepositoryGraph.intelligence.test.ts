import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  INTELLIGENCE_LIMIT,
  MAX_IMPACT_DEPTH,
  useRepositoryGraph,
} from "@/application/graph/useRepositoryGraph";
import * as graphApi from "@/infrastructure/api/graphApi";
import type {
  DependencyPath,
  FileGraphNode,
  GraphInsights,
  GraphNeighbor,
  GraphStatistics,
  ImpactAnalysis,
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
  projectedAt: null,
};

const fileA: FileGraphNode = {
  id: "n-file-a",
  kind: "file",
  repositoryId: REPO,
  path: "pkg/a.py",
  language: "python",
  hasSyntaxErrors: false,
};

const fileB: FileGraphNode = { ...fileA, id: "n-file-b", path: "pkg/b.py" };

const symbolNode: SymbolGraphNode = {
  id: "n-sym",
  kind: "symbol",
  repositoryId: REPO,
  name: "bark",
  qualifiedName: "pkg.a.bark",
  symbolKind: "function",
  fileId: "n-file-a",
  startLine: 1,
  endLine: 2,
};

const DEPENDENCIES: GraphNeighbor[] = [
  { node: fileB, relationshipKind: "imports", direction: "outgoing" },
];
const DEPENDENTS: GraphNeighbor[] = [
  { node: repoNode, relationshipKind: "contains", direction: "incoming" },
];

const IMPACT: ImpactAnalysis = {
  startingNodeId: fileA.id,
  direction: "upstream",
  maxDepth: 3,
  impactedNodes: [{ node: fileB, depth: 1, relationshipKind: "imports" }],
};

const PATH_FOUND: DependencyPath = {
  sourceId: fileA.id,
  targetId: fileB.id,
  found: true,
  nodes: [fileA, fileB],
  relationships: [
    {
      id: `${fileA.id}->${fileB.id}:imports`,
      sourceId: fileA.id,
      targetId: fileB.id,
      kind: "imports",
      dependencyEdgeId: null,
    },
  ],
  length: 1,
};

const PATH_NOT_FOUND: DependencyPath = {
  sourceId: fileA.id,
  targetId: fileB.id,
  found: false,
  nodes: [],
  relationships: [],
  length: null,
};

const STATS: GraphStatistics = {
  repositoryId: REPO,
  totalNodes: 3,
  totalFiles: 2,
  totalSymbols: 1,
  totalRelationships: 2,
  relationshipsByKind: [{ kind: "imports", count: 1 }],
  highestInDegree: [],
  highestOutDegree: [],
  projectedAt: null,
  freshness: "fresh",
  computedAt: "2026-08-22T00:00:00Z",
};

const INSIGHTS: GraphInsights = {
  repositoryId: REPO,
  mostConnectedFiles: [{ node: fileA, degree: 3 }],
  dependencyHotspots: [],
  isolatedNodes: [symbolNode],
  mutualImportPairs: [{ fileA, fileB }],
  unresolvedDependencyCount: 2,
  computedAt: "2026-08-22T00:00:00Z",
};

function render(enabled = true) {
  return renderHook(() => useRepositoryGraph(PROJECT, REPO, enabled));
}

/** Settle the initial graph load so per-selection assertions start from a clean slate. */
async function loaded(enabled = true) {
  const rendered = render(enabled);
  if (enabled) await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(graphApi, "fetchGraphNodes").mockResolvedValue([repoNode, fileA, fileB, symbolNode]);
  vi.spyOn(graphApi, "fetchGraphRelationships").mockResolvedValue([]);
  vi.spyOn(graphApi, "fetchGraphStatistics").mockResolvedValue(STATS);
  vi.spyOn(graphApi, "fetchGraphNeighbors").mockResolvedValue([]);
  vi.spyOn(graphApi, "fetchGraphInsights").mockResolvedValue(INSIGHTS);
  vi.spyOn(graphApi, "fetchNodeDependencies").mockResolvedValue(DEPENDENCIES);
  vi.spyOn(graphApi, "fetchNodeDependents").mockResolvedValue(DEPENDENTS);
  vi.spyOn(graphApi, "fetchNodeImpact").mockResolvedValue(IMPACT);
  vi.spyOn(graphApi, "fetchGraphPath").mockResolvedValue(PATH_FOUND);
});

describe("intelligence requests while locked", () => {
  it("issues no intelligence requests before projection", async () => {
    const { result } = await loaded(false);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(graphApi.fetchNodeDependencies).not.toHaveBeenCalled();
    expect(graphApi.fetchNodeDependents).not.toHaveBeenCalled();
    expect(graphApi.fetchGraphInsights).not.toHaveBeenCalled();
    expect(graphApi.fetchNodeImpact).not.toHaveBeenCalled();
    expect(graphApi.fetchGraphPath).not.toHaveBeenCalled();
  });
});

describe("insights", () => {
  it("loads once alongside the graph, not per node", async () => {
    const { result } = await loaded();

    await waitFor(() => expect(result.current.insights.data).toEqual(INSIGHTS));
    expect(graphApi.fetchGraphInsights).toHaveBeenCalledTimes(1);
  });

  it("surfaces an insights failure without breaking the graph", async () => {
    vi.spyOn(graphApi, "fetchGraphInsights").mockRejectedValue(new Error("insights failed"));
    const { result } = await loaded();

    await waitFor(() => expect(result.current.insights.error).toBe("insights failed"));
    expect(result.current.graph.nodes).toHaveLength(4);
    expect(result.current.error).toBeNull();
  });
});

describe("dependencies and dependents", () => {
  it("fetches neither until a node is selected", async () => {
    const { result } = await loaded();

    expect(graphApi.fetchNodeDependencies).not.toHaveBeenCalled();
    expect(graphApi.fetchNodeDependents).not.toHaveBeenCalled();
    expect(result.current.dependencies.data).toBeNull();
    expect(result.current.dependents.data).toBeNull();
  });

  it("fetches both for the selected node, once each", async () => {
    const { result } = await loaded();

    act(() => result.current.selectNode(fileA));

    await waitFor(() => expect(result.current.dependencies.data).toEqual(DEPENDENCIES));
    await waitFor(() => expect(result.current.dependents.data).toEqual(DEPENDENTS));
    expect(graphApi.fetchNodeDependencies).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchNodeDependencies).toHaveBeenCalledWith(
      PROJECT,
      REPO,
      fileA.id,
      INTELLIGENCE_LIMIT,
    );
    expect(graphApi.fetchNodeDependents).toHaveBeenCalledWith(
      PROJECT,
      REPO,
      fileA.id,
      INTELLIGENCE_LIMIT,
    );
  });

  it("issues one pair of requests per selection regardless of graph size", async () => {
    const many = Array.from({ length: 100 }, (_, i) => ({ ...symbolNode, id: `s${i}` }));
    vi.spyOn(graphApi, "fetchGraphNodes").mockResolvedValue(many);
    const { result } = await loaded();

    expect(graphApi.fetchNodeDependencies).not.toHaveBeenCalled();

    act(() => result.current.selectNode(many[42]));
    await waitFor(() => expect(result.current.dependencies.isLoading).toBe(false));

    expect(graphApi.fetchNodeDependencies).toHaveBeenCalledTimes(1);
    expect(graphApi.fetchNodeDependents).toHaveBeenCalledTimes(1);
  });

  it("replaces results when the selection changes, never showing the previous node's", async () => {
    const { result } = await loaded();

    act(() => result.current.selectNode(fileA));
    await waitFor(() => expect(result.current.dependencies.data).toEqual(DEPENDENCIES));

    vi.spyOn(graphApi, "fetchNodeDependencies").mockResolvedValue([]);
    act(() => result.current.selectNode(fileB));

    // Keyed on the node id, so the stale list is dropped immediately.
    await waitFor(() => expect(result.current.dependencies.data).toEqual([]));
    expect(graphApi.fetchNodeDependencies).toHaveBeenLastCalledWith(
      PROJECT,
      REPO,
      fileB.id,
      INTELLIGENCE_LIMIT,
    );
  });

  it("reports an empty dependency list distinctly from loading", async () => {
    vi.spyOn(graphApi, "fetchNodeDependencies").mockResolvedValue([]);
    const { result } = await loaded();

    act(() => result.current.selectNode(fileA));

    await waitFor(() => expect(result.current.dependencies.data).toEqual([]));
    expect(result.current.dependencies.isLoading).toBe(false);
    expect(result.current.dependencies.error).toBeNull();
  });

  it("keeps dependents working when dependencies fail", async () => {
    vi.spyOn(graphApi, "fetchNodeDependencies").mockRejectedValue(new Error("deps failed"));
    const { result } = await loaded();

    act(() => result.current.selectNode(fileA));

    await waitFor(() => expect(result.current.dependencies.error).toBe("deps failed"));
    await waitFor(() => expect(result.current.dependents.data).toEqual(DEPENDENTS));
    expect(result.current.error).toBeNull();
  });
});

describe("impact analysis", () => {
  it("never runs automatically", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    await waitFor(() => expect(result.current.dependencies.isLoading).toBe(false));

    expect(graphApi.fetchNodeImpact).not.toHaveBeenCalled();
    expect(result.current.impact.data).toBeNull();
  });

  it("runs with the chosen direction and depth", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));

    act(() => result.current.setImpactDirection("downstream"));
    act(() => result.current.setImpactDepth(5));
    await act(async () => {
      await result.current.impact.run();
    });

    expect(graphApi.fetchNodeImpact).toHaveBeenCalledWith(PROJECT, REPO, fileA.id, {
      direction: "downstream",
      depth: 5,
      limit: INTELLIGENCE_LIMIT,
    });
    expect(result.current.impact.data).toEqual(IMPACT);
  });

  it("clamps depth to what the schema accepts", async () => {
    const { result } = await loaded();

    act(() => result.current.setImpactDepth(0));
    expect(result.current.impactDepth).toBe(1);

    act(() => result.current.setImpactDepth(999));
    expect(result.current.impactDepth).toBe(MAX_IMPACT_DEPTH);

    act(() => result.current.setImpactDepth(Number.NaN));
    expect(result.current.impactDepth).toBe(1);
  });

  it("refuses to run without a selected node", async () => {
    const { result } = await loaded();

    await act(async () => {
      await result.current.impact.run();
    });

    expect(graphApi.fetchNodeImpact).not.toHaveBeenCalled();
    expect(result.current.impact.error).toMatch(/select a node/i);
  });

  it("surfaces a backend impact failure", async () => {
    vi.spyOn(graphApi, "fetchNodeImpact").mockRejectedValue(new Error("traversal exploded"));
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));

    await act(async () => {
      await result.current.impact.run();
    });

    expect(result.current.impact.error).toBe("traversal exploded");
    // The graph and the other sections are untouched.
    expect(result.current.graph.nodes).toHaveLength(4);
    expect(result.current.dependencies.error).toBeNull();
  });

  it("discards a previous node's impact when the selection changes", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    await act(async () => {
      await result.current.impact.run();
    });
    expect(result.current.impact.data).toEqual(IMPACT);

    act(() => result.current.selectNode(fileB));

    // Stale impact must not remain under a different node.
    expect(result.current.impact.data).toBeNull();
    expect(result.current.impact.error).toBeNull();
  });
});

describe("path finding", () => {
  it("cannot run without both endpoints", async () => {
    const { result } = await loaded();
    expect(result.current.canRunPath).toBe(false);

    act(() => result.current.selectNode(fileA));
    expect(result.current.canRunPath).toBe(false);

    act(() => result.current.selectPathTarget(fileB));
    expect(result.current.canRunPath).toBe(true);
  });

  it("never runs automatically", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));
    await waitFor(() => expect(result.current.dependencies.isLoading).toBe(false));

    expect(graphApi.fetchGraphPath).not.toHaveBeenCalled();
  });

  it("requests source, target, and depth", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));
    act(() => result.current.setPathDepth(4));

    await act(async () => {
      await result.current.path.run();
    });

    expect(graphApi.fetchGraphPath).toHaveBeenCalledWith(PROJECT, REPO, fileA.id, fileB.id, 4);
    expect(result.current.path.data).toEqual(PATH_FOUND);
  });

  it("represents a genuine no-path answer as a result, not an error", async () => {
    vi.spyOn(graphApi, "fetchGraphPath").mockResolvedValue(PATH_NOT_FOUND);
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));

    await act(async () => {
      await result.current.path.run();
    });

    expect(result.current.path.data?.found).toBe(false);
    expect(result.current.path.data?.length).toBeNull();
    expect(result.current.path.error).toBeNull();
  });

  it("errors clearly when no target is pinned", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));

    await act(async () => {
      await result.current.path.run();
    });

    expect(graphApi.fetchGraphPath).not.toHaveBeenCalled();
    expect(result.current.path.error).toMatch(/target/i);
  });

  it("surfaces a backend path failure", async () => {
    vi.spyOn(graphApi, "fetchGraphPath").mockRejectedValue(new Error("path exploded"));
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));

    await act(async () => {
      await result.current.path.run();
    });

    expect(result.current.path.error).toBe("path exploded");
    expect(result.current.graph.nodes).toHaveLength(4);
  });

  it("discards a stale path when the source selection changes", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));
    await act(async () => {
      await result.current.path.run();
    });
    expect(result.current.path.data).toEqual(PATH_FOUND);

    act(() => result.current.selectNode(symbolNode));

    expect(result.current.path.data).toBeNull();
  });

  it("discards a stale path when the target changes", async () => {
    const { result } = await loaded();
    act(() => result.current.selectNode(fileA));
    act(() => result.current.selectPathTarget(fileB));
    await act(async () => {
      await result.current.path.run();
    });

    act(() => result.current.selectPathTarget(symbolNode));

    expect(result.current.path.data).toBeNull();
    expect(result.current.pathTarget).toEqual(symbolNode);
  });

  it("clamps path depth", async () => {
    const { result } = await loaded();

    act(() => result.current.setPathDepth(0));
    expect(result.current.pathDepth).toBe(1);
  });
});

describe("tab state", () => {
  it("starts on overview and switches without issuing requests", async () => {
    const { result } = await loaded();
    const before = graphApi.fetchNodeDependencies as unknown as { mock: { calls: unknown[] } };

    expect(result.current.activeTab).toBe("overview");
    act(() => result.current.setActiveTab("impact"));

    expect(result.current.activeTab).toBe("impact");
    // Switching tabs is a view change, not a fetch.
    expect(before.mock.calls).toHaveLength(0);
  });
});
