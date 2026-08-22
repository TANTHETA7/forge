import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "@/infrastructure/api/client";
import {
  fetchGraphNeighbors,
  fetchGraphNodes,
  fetchGraphRelationships,
  fetchGraphStatistics,
} from "@/infrastructure/api/graphApi";

const PROJECT = "11111111-1111-1111-1111-111111111111";
const REPO = "22222222-2222-2222-2222-222222222222";
const BASE = `/projects/${PROJECT}/repositories/${REPO}`;

// Shapes copied from a real projection's responses.
const REPO_NODE_DTO = {
  id: "n-repo",
  kind: "repository",
  repository_id: REPO,
  properties: {
    display_name: "graphrepo",
    project_id: PROJECT,
    projected_at: "2026-08-21T17:54:26.665000+00:00",
  },
};

const FILE_NODE_DTO = {
  id: "n-file",
  kind: "file",
  repository_id: REPO,
  properties: { path: "pkg/broken.py", has_syntax_errors: true, language: "python" },
};

const SYMBOL_NODE_DTO = {
  id: "n-sym",
  kind: "symbol",
  repository_id: REPO,
  properties: {
    name: "Model06",
    qualified_name: "Model06",
    kind: "class",
    file_id: "f92dfa01-92b1-517b-86a0-5f274e10a754",
    start_line: 19,
    end_line: 20,
  },
};

let apiGet: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.restoreAllMocks();
  apiGet = vi.spyOn(client, "apiGet");
});

describe("fetchGraphNodes mapping", () => {
  it("maps a repository node's properties into named fields", async () => {
    apiGet.mockResolvedValue([REPO_NODE_DTO]);

    const [node] = await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(node).toEqual({
      id: "n-repo",
      kind: "repository",
      repositoryId: REPO,
      displayName: "graphrepo",
      projectId: PROJECT,
      projectedAt: "2026-08-21T17:54:26.665000+00:00",
    });
  });

  it("maps a file node, including its syntax-error flag", async () => {
    apiGet.mockResolvedValue([FILE_NODE_DTO]);

    const [node] = await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(node).toEqual({
      id: "n-file",
      kind: "file",
      repositoryId: REPO,
      path: "pkg/broken.py",
      language: "python",
      hasSyntaxErrors: true,
    });
  });

  it("maps a symbol node, keeping its own kind separate from the node kind", async () => {
    apiGet.mockResolvedValue([SYMBOL_NODE_DTO]);

    const [node] = await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(node).toEqual({
      id: "n-sym",
      kind: "symbol",
      repositoryId: REPO,
      name: "Model06",
      qualifiedName: "Model06",
      symbolKind: "class",
      fileId: "f92dfa01-92b1-517b-86a0-5f274e10a754",
      startLine: 19,
      endLine: 20,
    });
  });

  it("represents an unrecognized kind explicitly rather than mislabelling it", async () => {
    apiGet.mockResolvedValue([
      { id: "n-x", kind: "package", repository_id: REPO, properties: { name: "x" } },
    ]);

    const [node] = await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(node).toEqual({ id: "n-x", kind: "unknown", repositoryId: REPO, rawKind: "package" });
  });

  it("tolerates missing or wrongly-typed properties without throwing", async () => {
    apiGet.mockResolvedValue([
      { id: "n-file", kind: "file", repository_id: REPO, properties: { path: 42 } },
    ]);

    const [node] = await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(node).toMatchObject({ kind: "file", path: null, language: null, hasSyntaxErrors: false });
  });

  it("sends the bounded limit and offset", async () => {
    apiGet.mockResolvedValue([]);

    await fetchGraphNodes(PROJECT, REPO, { limit: 150, offset: 0 });

    expect(apiGet).toHaveBeenCalledWith(`${BASE}/graph/nodes?limit=150&offset=0`);
  });
});

describe("fetchGraphRelationships mapping", () => {
  it("composes a stable id from source, target, and kind", async () => {
    apiGet.mockResolvedValue([
      {
        source_id: "a",
        target_id: "b",
        kind: "contains",
        repository_id: REPO,
        dependency_edge_id: null,
        properties: {},
      },
    ]);

    const [rel] = await fetchGraphRelationships(PROJECT, REPO, { limit: 300, offset: 0 });

    expect(rel).toEqual({
      id: "a->b:contains",
      sourceId: "a",
      targetId: "b",
      kind: "contains",
      dependencyEdgeId: null,
    });
  });

  it("keeps the dependency edge id when the backend provides one", async () => {
    apiGet.mockResolvedValue([
      {
        source_id: "a",
        target_id: "b",
        kind: "calls",
        repository_id: REPO,
        dependency_edge_id: "edge-1",
        properties: {},
      },
    ]);

    const [rel] = await fetchGraphRelationships(PROJECT, REPO, { limit: 300, offset: 0 });

    expect(rel.dependencyEdgeId).toBe("edge-1");
    expect(rel.id).toBe("a->b:calls");
  });

  it("gives different relationship kinds between the same pair distinct ids", async () => {
    apiGet.mockResolvedValue([
      {
        source_id: "a",
        target_id: "b",
        kind: "contains",
        repository_id: REPO,
        dependency_edge_id: null,
        properties: {},
      },
      {
        source_id: "a",
        target_id: "b",
        kind: "defines",
        repository_id: REPO,
        dependency_edge_id: null,
        properties: {},
      },
    ]);

    const rels = await fetchGraphRelationships(PROJECT, REPO, { limit: 300, offset: 0 });

    expect(new Set(rels.map((r) => r.id)).size).toBe(2);
  });
});

describe("fetchGraphNeighbors mapping", () => {
  it("maps the nested node and normalizes direction", async () => {
    apiGet.mockResolvedValue([
      { node: FILE_NODE_DTO, relationship_kind: "contains", direction: "incoming" },
      { node: SYMBOL_NODE_DTO, relationship_kind: "defines", direction: "outgoing" },
    ]);

    const neighbors = await fetchGraphNeighbors(PROJECT, REPO, "n-file", 50);

    expect(neighbors).toHaveLength(2);
    expect(neighbors[0]).toMatchObject({
      relationshipKind: "contains",
      direction: "incoming",
      node: { kind: "file", path: "pkg/broken.py" },
    });
    expect(neighbors[1]).toMatchObject({ direction: "outgoing", node: { kind: "symbol" } });
  });

  it("keeps a neighbor with an unexpected direction rather than dropping it", async () => {
    apiGet.mockResolvedValue([
      { node: FILE_NODE_DTO, relationship_kind: "contains", direction: "sideways" },
    ]);

    const neighbors = await fetchGraphNeighbors(PROJECT, REPO, "n-file", 50);

    expect(neighbors).toHaveLength(1);
    expect(neighbors[0].direction).toBe("incoming");
  });

  it("requests the given node with a bounded limit", async () => {
    apiGet.mockResolvedValue([]);

    await fetchGraphNeighbors(PROJECT, REPO, "n-file", 50);

    expect(apiGet).toHaveBeenCalledWith(`${BASE}/graph/neighbors/n-file?limit=50`);
  });
});

describe("fetchGraphStatistics mapping", () => {
  it("maps totals, per-kind counts, and degree rankings, keeping zero counts", async () => {
    apiGet.mockResolvedValue({
      repository_id: REPO,
      total_nodes: 45,
      total_files: 5,
      total_symbols: 39,
      total_relationships: 60,
      relationships_by_kind: [
        { kind: "contains", count: 17 },
        { kind: "inherits", count: 0 },
      ],
      highest_in_degree: [{ node: FILE_NODE_DTO, degree: 12 }],
      highest_out_degree: [{ node: REPO_NODE_DTO, degree: 5 }],
      projected_at: "2026-08-21T17:54:26.665000Z",
      freshness: "fresh",
      computed_at: "2026-08-21T17:54:37.923172Z",
    });

    const stats = await fetchGraphStatistics(PROJECT, REPO);

    expect(stats).toMatchObject({
      totalNodes: 45,
      totalFiles: 5,
      totalSymbols: 39,
      totalRelationships: 60,
      freshness: "fresh",
    });
    expect(stats.relationshipsByKind).toEqual([
      { kind: "contains", count: 17 },
      { kind: "inherits", count: 0 },
    ]);
    // Degree rankings are real backend output and must not be dropped.
    expect(stats.highestInDegree).toEqual([
      { node: expect.objectContaining({ kind: "file", path: "pkg/broken.py" }), degree: 12 },
    ]);
    expect(stats.highestOutDegree[0].degree).toBe(5);
  });
});
