/**
 * useRepositoryGraph hook.
 *
 * Purpose:       Load a projected repository's graph, track the selected node, and
 *                fetch that node's neighbors.
 * Responsibility: React state and request orchestration — no fetch details, no
 *                 layout, no rendering.
 * Why it exists: Keeps the request budget explicit and bounded. Opening the graph
 *                costs exactly three requests (nodes, relationships, statistics);
 *                selecting a node costs exactly one (its neighbors). Nothing is
 *                fetched per node, so there is no N+1 — the whole point of taking
 *                neighbors from `/graph/neighbors/{id}` on demand rather than
 *                walking every node.
 * Depends on:    application/shared/useAsyncData.ts, infrastructure/api/graphApi.ts,
 *                domain/graph/types.ts.
 * Depended on by: presentation/graph/GraphPanel.tsx.
 */

import { useCallback, useMemo, useState } from "react";

import { useAsyncAction } from "@/application/shared/useAsyncAction";
import { useAsyncData } from "@/application/shared/useAsyncData";
import {
  fetchGraphInsights,
  fetchGraphNeighbors,
  fetchGraphNodes,
  fetchGraphPath,
  fetchGraphRelationships,
  fetchGraphStatistics,
  fetchNodeDependencies,
  fetchNodeDependents,
  fetchNodeImpact,
} from "@/infrastructure/api/graphApi";
import type { GraphNode, GraphRelationship, ImpactDirection } from "@/domain/graph/types";

/**
 * Bounds for the initial load. Deliberately explicit rather than "fetch everything":
 * a real repository's graph is far larger than is readable or renderable at once, and
 * `/graph/nodes` pages at 100 by default. When a repository exceeds these, the UI says
 * so instead of implying the whole graph is on screen.
 */
export const GRAPH_NODE_LIMIT = 150;
export const GRAPH_RELATIONSHIP_LIMIT = 300;
export const NEIGHBOR_LIMIT = 50;
export const INTELLIGENCE_LIMIT = 100;
export const INSIGHTS_LIMIT = 10;

/** Depth bounds the UI enforces before sending; the schema's own minimum is 1. */
export const MIN_DEPTH = 1;
export const MAX_IMPACT_DEPTH = 10;
export const MAX_PATH_DEPTH = 10;
export const DEFAULT_IMPACT_DEPTH = 3;
export const DEFAULT_PATH_DEPTH = 6;

/** Sections of the selected-node panel. */
export type NodeTab = "overview" | "dependencies" | "dependents" | "impact" | "path";

export interface RenderableGraph {
  nodes: GraphNode[];
  /** Relationships whose endpoints are both present in `nodes`. */
  relationships: GraphRelationship[];
  /**
   * Relationships omitted because an endpoint fell outside the loaded node page.
   * Surfaced rather than silently dropped — an edge to a node that is not on screen
   * cannot be drawn, and hiding that fact would misrepresent the graph.
   */
  omittedRelationshipCount: number;
}

const EMPTY_GRAPH: RenderableGraph = {
  nodes: [],
  relationships: [],
  omittedRelationshipCount: 0,
};

export function useRepositoryGraph(
  projectId: string | null,
  repositoryId: string | null,
  enabled: boolean,
) {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [activeTab, setActiveTab] = useState<NodeTab>("overview");

  // Impact and path parameters. Only values the backend accepts are representable:
  // direction is the `DependencyDirection` union, and depth is clamped on the way in.
  const [impactDirection, setImpactDirection] = useState<ImpactDirection>("upstream");
  const [impactDepth, setImpactDepthState] = useState(DEFAULT_IMPACT_DEPTH);
  const [pathTarget, setPathTarget] = useState<GraphNode | null>(null);
  const [pathDepth, setPathDepthState] = useState(DEFAULT_PATH_DEPTH);

  const scoped = enabled && projectId !== null && repositoryId !== null;
  const scope = `${projectId ?? "-"}:${repositoryId ?? "-"}`;

  const nodes = useAsyncData(
    `graph-nodes:${scope}`,
    () =>
      fetchGraphNodes(projectId as string, repositoryId as string, {
        limit: GRAPH_NODE_LIMIT,
        offset: 0,
      }),
    scoped,
  );

  const relationships = useAsyncData(
    `graph-rels:${scope}`,
    () =>
      fetchGraphRelationships(projectId as string, repositoryId as string, {
        limit: GRAPH_RELATIONSHIP_LIMIT,
        offset: 0,
      }),
    scoped,
  );

  const statistics = useAsyncData(
    `graph-stats:${scope}`,
    () => fetchGraphStatistics(projectId as string, repositoryId as string),
    scoped,
  );

  const neighbors = useAsyncData(
    `graph-neighbors:${scope}:${selectedNode?.id ?? "-"}`,
    () =>
      fetchGraphNeighbors(
        projectId as string,
        repositoryId as string,
        selectedNode?.id as string,
        NEIGHBOR_LIMIT,
      ),
    scoped && selectedNode !== null,
  );

  // Directional intelligence for the selected node. Keyed on the node id, so a new
  // selection replaces the data rather than leaving the previous node's results on
  // screen, and disabled entirely when nothing is selected.
  const dependencies = useAsyncData(
    `graph-deps:${scope}:${selectedNode?.id ?? "-"}`,
    () =>
      fetchNodeDependencies(
        projectId as string,
        repositoryId as string,
        selectedNode?.id as string,
        INTELLIGENCE_LIMIT,
      ),
    scoped && selectedNode !== null,
  );

  const dependents = useAsyncData(
    `graph-dependents:${scope}:${selectedNode?.id ?? "-"}`,
    () =>
      fetchNodeDependents(
        projectId as string,
        repositoryId as string,
        selectedNode?.id as string,
        INTELLIGENCE_LIMIT,
      ),
    scoped && selectedNode !== null,
  );

  /** Repository-level insights — one request alongside the initial graph load. */
  const insights = useAsyncData(
    `graph-insights:${scope}`,
    () => fetchGraphInsights(projectId as string, repositoryId as string, INSIGHTS_LIMIT),
    scoped,
  );

  // Impact and path are explicit user actions, so they use the triggered-action hook
  // rather than firing on selection. Nothing is requested until the user asks.
  const impactAction = useAsyncAction(async () => {
    if (!projectId || !repositoryId || !selectedNode) {
      throw new Error("Select a node before running impact analysis");
    }
    return fetchNodeImpact(projectId, repositoryId, selectedNode.id, {
      direction: impactDirection,
      depth: impactDepth,
      limit: INTELLIGENCE_LIMIT,
    });
  });

  const pathAction = useAsyncAction(async () => {
    if (!projectId || !repositoryId || !selectedNode) {
      throw new Error("Select a source node first");
    }
    if (!pathTarget) throw new Error("Choose a target node first");
    return fetchGraphPath(projectId, repositoryId, selectedNode.id, pathTarget.id, pathDepth);
  });

  /**
   * Join nodes and relationships once per load rather than per render. O(N + E) via a
   * Set of loaded ids — no pairwise comparison.
   */
  const graph = useMemo<RenderableGraph>(() => {
    const loadedNodes = nodes.data;
    if (!loadedNodes) return EMPTY_GRAPH;

    const ids = new Set(loadedNodes.map((node) => node.id));
    const all = relationships.data ?? [];
    const renderable = all.filter((rel) => ids.has(rel.sourceId) && ids.has(rel.targetId));

    return {
      nodes: loadedNodes,
      relationships: renderable,
      omittedRelationshipCount: all.length - renderable.length,
    };
  }, [nodes.data, relationships.data]);

  // Destructured so the stable `reset` identities can be dependencies in their own
  // right — the action objects themselves are new on every render.
  const { reset: resetImpact } = impactAction;
  const { reset: resetPath } = pathAction;

  /**
   * Selection takes the whole node rather than an id: a neighbor may lie outside the
   * loaded page, and `/graph/neighbors` already returns full node objects, so this
   * avoids both a lookup miss and an extra request.
   *
   * Impact and path results are discarded here. They are keyed to no node id of their
   * own — being triggered rather than derived — so without this reset the previous
   * node's impact would stay on screen under a new selection.
   */
  const selectNode = useCallback(
    (node: GraphNode | null) => {
      setSelectedNode(node);
      resetImpact();
      resetPath();
    },
    [resetImpact, resetPath],
  );

  /** Make the currently selected node the path target. */
  const selectPathTarget = useCallback(
    (node: GraphNode | null) => {
      setPathTarget(node);
      resetPath();
    },
    [resetPath],
  );

  const clampDepth = (value: number, max: number) =>
    Number.isFinite(value) ? Math.min(Math.max(Math.trunc(value), MIN_DEPTH), max) : MIN_DEPTH;

  const setImpactDepth = useCallback(
    (value: number) => setImpactDepthState(clampDepth(value, MAX_IMPACT_DEPTH)),
    [],
  );
  const setPathDepth = useCallback(
    (value: number) => setPathDepthState(clampDepth(value, MAX_PATH_DEPTH)),
    [],
  );

  const isLoading = nodes.isLoading || relationships.isLoading;
  const error = nodes.error ?? relationships.error;
  const isEmpty =
    !isLoading && error === null && nodes.data !== null && nodes.data.length === 0;

  /** True when the projection is larger than this bounded view. */
  const isTruncated =
    statistics.data !== null &&
    nodes.data !== null &&
    statistics.data.totalNodes > nodes.data.length;

  return {
    graph,
    isLoading,
    error,
    isEmpty,
    isTruncated,
    statistics,
    insights,
    selectedNode,
    selectNode,
    activeTab,
    setActiveTab,
    neighbors,
    dependencies,
    dependents,
    // Impact
    impact: impactAction,
    impactDirection,
    setImpactDirection,
    impactDepth,
    setImpactDepth,
    // Path
    path: pathAction,
    pathTarget,
    selectPathTarget,
    pathDepth,
    setPathDepth,
    canRunPath: selectedNode !== null && pathTarget !== null,
  };
}
