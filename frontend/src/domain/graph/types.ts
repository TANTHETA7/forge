/**
 * Graph domain types.
 *
 * Purpose:       Mirror the backend's `GraphNodeResponse`,
 *                `GraphRelationshipResponse`, `GraphNeighborResponse`, and
 *                `GraphStatisticsResponse` contracts as TypeScript types.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: The wire format carries per-node metadata in an untyped
 *                `properties` bag whose keys differ by node kind (verified live:
 *                repository → display_name/project_id/projected_at; file →
 *                path/language/has_syntax_errors; symbol →
 *                name/qualified_name/kind/file_id/start_line/end_line). Modelling
 *                that as a discriminated union means presentation components read
 *                named, typed fields instead of indexing a `Record` — the bag never
 *                leaves the API client.
 * Depended on by: infrastructure/api/graphApi.ts,
 *                 application/graph/useRepositoryGraph.ts, presentation/graph/*.
 */

/** Mirrors backend `GraphNodeKind`. */
export type GraphNodeKind = "repository" | "file" | "symbol";

/** Mirrors backend `GraphRelationshipKind`. */
export type GraphRelationshipKind = "contains" | "defines" | "imports" | "calls" | "inherits";

export const GRAPH_RELATIONSHIP_KINDS: readonly GraphRelationshipKind[] = [
  "contains",
  "defines",
  "imports",
  "calls",
  "inherits",
];

/** Mirrors the `direction` field of `GraphNeighborResponse` (verified live). */
export type NeighborDirection = "incoming" | "outgoing";

interface GraphNodeBase {
  id: string;
  repositoryId: string;
}

export interface RepositoryGraphNode extends GraphNodeBase {
  kind: "repository";
  displayName: string | null;
  projectId: string | null;
  projectedAt: string | null;
}

export interface FileGraphNode extends GraphNodeBase {
  kind: "file";
  path: string | null;
  language: string | null;
  hasSyntaxErrors: boolean;
}

export interface SymbolGraphNode extends GraphNodeBase {
  kind: "symbol";
  name: string | null;
  qualifiedName: string | null;
  /** The symbol's own kind — function / class / method — not the graph node kind. */
  symbolKind: string | null;
  fileId: string | null;
  startLine: number | null;
  endLine: number | null;
}

/**
 * A node whose `kind` this build does not recognize. The backend serializes its
 * `StrEnum` as a plain string, so a future node label would arrive as an unknown
 * value; keeping it as an explicit variant means such a node renders neutrally
 * instead of being silently mislabelled as one of the known kinds.
 */
export interface UnknownGraphNode extends GraphNodeBase {
  kind: "unknown";
  rawKind: string;
}

export type GraphNode =
  | RepositoryGraphNode
  | FileGraphNode
  | SymbolGraphNode
  | UnknownGraphNode;

export interface GraphRelationship {
  /**
   * Composed as `sourceId->targetId:kind`. The API returns no identifier for a
   * relationship, and `dependency_edge_id` is null for the structural CONTAINS and
   * DEFINES edges, so this triple is the only stable identity available — and it is
   * what React Flow keys edges on.
   */
  id: string;
  sourceId: string;
  targetId: string;
  /** A `GraphRelationshipKind` in practice; typed as the wire types it. */
  kind: string;
  /** Present for Phase 4 dependency edges, null for structural containment. */
  dependencyEdgeId: string | null;
}

export interface GraphNeighbor {
  node: GraphNode;
  relationshipKind: string;
  direction: NeighborDirection;
}

export interface RelationshipKindCount {
  kind: string;
  count: number;
}

/** A node paired with its degree — used by statistics and insights alike. */
export interface NodeDegree {
  node: GraphNode;
  degree: number;
}

export interface GraphStatistics {
  repositoryId: string;
  totalNodes: number;
  totalFiles: number;
  totalSymbols: number;
  totalRelationships: number;
  relationshipsByKind: RelationshipKindCount[];
  highestInDegree: NodeDegree[];
  highestOutDegree: NodeDegree[];
  projectedAt: string | null;
  freshness: string;
  computedAt: string;
}

/** Mirrors backend `DependencyDirection` — the only two values `/impact` accepts. */
export type ImpactDirection = "upstream" | "downstream";

export const IMPACT_DIRECTIONS: readonly ImpactDirection[] = ["upstream", "downstream"];

export interface ImpactedNode {
  node: GraphNode;
  /** Hops from the starting node. The backend returns the shortest depth it found. */
  depth: number;
  relationshipKind: string;
}

export interface ImpactAnalysis {
  startingNodeId: string;
  direction: string;
  maxDepth: number;
  impactedNodes: ImpactedNode[];
}

export interface DependencyPath {
  sourceId: string;
  targetId: string;
  found: boolean;
  /** Ordered from source to target. Empty when `found` is false. */
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  /** Hop count; null when no path was found. */
  length: number | null;
}

export interface MutualImportPair {
  fileA: GraphNode;
  fileB: GraphNode;
}

export interface GraphInsights {
  repositoryId: string;
  mostConnectedFiles: NodeDegree[];
  dependencyHotspots: NodeDegree[];
  isolatedNodes: GraphNode[];
  mutualImportPairs: MutualImportPair[];
  unresolvedDependencyCount: number;
  computedAt: string;
}

/** Human-readable label for a node, used by the canvas and the details panel. */
export function graphNodeLabel(node: GraphNode): string {
  switch (node.kind) {
    case "repository":
      return node.displayName ?? "repository";
    case "file":
      return node.path ?? "file";
    case "symbol":
      return node.name ?? node.qualifiedName ?? "symbol";
    default:
      return node.rawKind;
  }
}
