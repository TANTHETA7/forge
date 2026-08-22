/**
 * Graph API client.
 *
 * Purpose:       Read a projected repository's graph — nodes, relationships, one
 *                node's neighbors, and summary statistics — translating the wire
 *                format into domain types.
 * Responsibility: The four graph read endpoints. No orchestration, no layout.
 * Why it exists: The untyped `properties` bag is unpacked here, once, so nothing
 *                downstream indexes it by string key.
 *
 * Contract notes, taken from the live schema and verified against a real projection:
 *   - `/graph/nodes` accepts `kind` (repository|file|symbol), `limit` (default 100),
 *     `offset`. `/graph/dependencies` accepts `kind`
 *     (contains|defines|imports|calls|inherits), `limit`, `offset`.
 *   - `/graph/neighbors/{id}` accepts `direction` (incoming|outgoing|both, default
 *     both) and `limit`. Its response `direction` is incoming|outgoing.
 *   - Relationships carry no id; `dependency_edge_id` is null for structural edges.
 *   - Neither list endpoint returns a total count. `/graph/statistics` does, and is
 *     the only trustworthy source for repository-wide totals.
 *
 * Depends on:    infrastructure/api/client.ts, wire.ts, domain/graph/types.ts.
 * Depended on by: application/graph/useRepositoryGraph.ts.
 */

import { apiGet } from "@/infrastructure/api/client";
import { repositoryPath } from "@/infrastructure/api/wire";
import type {
  DependencyPath,
  GraphInsights,
  GraphNeighbor,
  GraphNode,
  GraphRelationship,
  GraphStatistics,
  ImpactAnalysis,
  ImpactDirection,
  NeighborDirection,
  NodeDegree,
} from "@/domain/graph/types";

/** The wire's property bag: scalars only, keys varying by node kind. */
type PropertyBag = Record<string, string | number | boolean | null>;

interface GraphNodeDto {
  id: string;
  kind: string;
  repository_id: string;
  properties: PropertyBag;
}

interface GraphRelationshipDto {
  source_id: string;
  target_id: string;
  kind: string;
  repository_id: string;
  dependency_edge_id: string | null;
  properties: PropertyBag;
}

interface GraphNeighborDto {
  node: GraphNodeDto;
  relationship_kind: string;
  direction: string;
}

interface NodeDegreeDto {
  node: GraphNodeDto;
  degree: number;
}

interface GraphStatisticsDto {
  repository_id: string;
  total_nodes: number;
  total_files: number;
  total_symbols: number;
  total_relationships: number;
  relationships_by_kind: { kind: string; count: number }[];
  highest_in_degree: NodeDegreeDto[];
  highest_out_degree: NodeDegreeDto[];
  projected_at: string | null;
  freshness: string;
  computed_at: string;
}

interface ImpactAnalysisDto {
  starting_node_id: string;
  direction: string;
  max_depth: number;
  impacted_nodes: { node: GraphNodeDto; depth: number; relationship_kind: string }[];
}

interface DependencyPathDto {
  source_id: string;
  target_id: string;
  found: boolean;
  nodes: GraphNodeDto[];
  relationships: GraphRelationshipDto[];
  length: number | null;
}

interface GraphInsightsDto {
  repository_id: string;
  most_connected_files: NodeDegreeDto[];
  dependency_hotspots: NodeDegreeDto[];
  isolated_nodes: GraphNodeDto[];
  mutual_import_pairs: { file_a: GraphNodeDto; file_b: GraphNodeDto }[];
  unresolved_dependency_count: number;
  computed_at: string;
}

// Property readers. The bag is `unknown`-ish by nature, so each value is checked
// rather than cast — a missing or wrongly-typed property becomes null, never a crash.
function str(bag: PropertyBag, key: string): string | null {
  const value = bag[key];
  return typeof value === "string" ? value : null;
}

function num(bag: PropertyBag, key: string): number | null {
  const value = bag[key];
  return typeof value === "number" ? value : null;
}

function bool(bag: PropertyBag, key: string): boolean {
  return bag[key] === true;
}

function toNodeDegree(dto: NodeDegreeDto): NodeDegree {
  return { node: toGraphNode(dto.node), degree: dto.degree };
}

export function toGraphNode(dto: GraphNodeDto): GraphNode {
  const base = { id: dto.id, repositoryId: dto.repository_id };

  switch (dto.kind) {
    case "repository":
      return {
        ...base,
        kind: "repository",
        displayName: str(dto.properties, "display_name"),
        projectId: str(dto.properties, "project_id"),
        projectedAt: str(dto.properties, "projected_at"),
      };
    case "file":
      return {
        ...base,
        kind: "file",
        path: str(dto.properties, "path"),
        language: str(dto.properties, "language"),
        hasSyntaxErrors: bool(dto.properties, "has_syntax_errors"),
      };
    case "symbol":
      return {
        ...base,
        kind: "symbol",
        name: str(dto.properties, "name"),
        qualifiedName: str(dto.properties, "qualified_name"),
        symbolKind: str(dto.properties, "kind"),
        fileId: str(dto.properties, "file_id"),
        startLine: num(dto.properties, "start_line"),
        endLine: num(dto.properties, "end_line"),
      };
    default:
      return { ...base, kind: "unknown", rawKind: dto.kind };
  }
}

export function toGraphRelationship(dto: GraphRelationshipDto): GraphRelationship {
  return {
    id: `${dto.source_id}->${dto.target_id}:${dto.kind}`,
    sourceId: dto.source_id,
    targetId: dto.target_id,
    kind: dto.kind,
    dependencyEdgeId: dto.dependency_edge_id,
  };
}

export interface GraphPageQuery {
  limit: number;
  offset: number;
}

export async function fetchGraphNodes(
  projectId: string,
  repositoryId: string,
  query: GraphPageQuery,
): Promise<GraphNode[]> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  const dtos = await apiGet<GraphNodeDto[]>(
    `${repositoryPath(projectId, repositoryId)}/graph/nodes?${params.toString()}`,
  );
  return dtos.map(toGraphNode);
}

export async function fetchGraphRelationships(
  projectId: string,
  repositoryId: string,
  query: GraphPageQuery,
): Promise<GraphRelationship[]> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  const dtos = await apiGet<GraphRelationshipDto[]>(
    `${repositoryPath(projectId, repositoryId)}/graph/dependencies?${params.toString()}`,
  );
  return dtos.map(toGraphRelationship);
}

/**
 * Map one neighbor entry. Shared by `/graph/neighbors/{id}`,
 * `/graph/nodes/{id}/dependencies`, and `/graph/nodes/{id}/dependents` — all three
 * return the same `GraphNeighborResponse` shape.
 */
function toGraphNeighbor(dto: GraphNeighborDto): GraphNeighbor {
  return {
    node: toGraphNode(dto.node),
    relationshipKind: dto.relationship_kind,
    // Only two values are documented; anything else is reported as incoming rather
    // than dropping the neighbor.
    direction: (dto.direction === "outgoing" ? "outgoing" : "incoming") as NeighborDirection,
  };
}

/** Neighbors of one node. Called only for a selected node — never per row. */
export async function fetchGraphNeighbors(
  projectId: string,
  repositoryId: string,
  nodeId: string,
  limit: number,
): Promise<GraphNeighbor[]> {
  const dtos = await apiGet<GraphNeighborDto[]>(
    `${repositoryPath(projectId, repositoryId)}/graph/neighbors/${nodeId}?limit=${limit}`,
  );
  return dtos.map(toGraphNeighbor);
}

/**
 * What the given node depends on. Scoped to one node by construction — there is no
 * bulk variant, and calling this per graph node would be the N+1 this design avoids.
 */
export async function fetchNodeDependencies(
  projectId: string,
  repositoryId: string,
  nodeId: string,
  limit: number,
): Promise<GraphNeighbor[]> {
  const dtos = await apiGet<GraphNeighborDto[]>(
    `${repositoryPath(projectId, repositoryId)}/graph/nodes/${nodeId}/dependencies?limit=${limit}`,
  );
  return dtos.map(toGraphNeighbor);
}

/** What depends on the given node. */
export async function fetchNodeDependents(
  projectId: string,
  repositoryId: string,
  nodeId: string,
  limit: number,
): Promise<GraphNeighbor[]> {
  const dtos = await apiGet<GraphNeighborDto[]>(
    `${repositoryPath(projectId, repositoryId)}/graph/nodes/${nodeId}/dependents?limit=${limit}`,
  );
  return dtos.map(toGraphNeighbor);
}

export interface ImpactQuery {
  /** `upstream` or `downstream` — the only values `DependencyDirection` allows. */
  direction: ImpactDirection;
  /** Minimum 1 per the schema; the backend's own default is 3. */
  depth: number;
  limit: number;
}

/**
 * Multi-hop impact analysis, run by Neo4j. Deliberately not reimplemented client-side:
 * the traversal belongs in the graph database, not the browser.
 */
export async function fetchNodeImpact(
  projectId: string,
  repositoryId: string,
  nodeId: string,
  query: ImpactQuery,
): Promise<ImpactAnalysis> {
  const params = new URLSearchParams({
    direction: query.direction,
    depth: String(query.depth),
    limit: String(query.limit),
  });
  const dto = await apiGet<ImpactAnalysisDto>(
    `${repositoryPath(projectId, repositoryId)}/graph/nodes/${nodeId}/impact?${params.toString()}`,
  );
  return {
    startingNodeId: dto.starting_node_id,
    direction: dto.direction,
    maxDepth: dto.max_depth,
    impactedNodes: dto.impacted_nodes.map((entry) => ({
      node: toGraphNode(entry.node),
      depth: entry.depth,
      relationshipKind: entry.relationship_kind,
    })),
  };
}

/**
 * Shortest dependency path between two nodes. `source_id` and `target_id` are both
 * required; `found` is false with an empty node list and a null length when there is
 * no path within `depth`.
 */
export async function fetchGraphPath(
  projectId: string,
  repositoryId: string,
  sourceId: string,
  targetId: string,
  depth: number,
): Promise<DependencyPath> {
  const params = new URLSearchParams({
    source_id: sourceId,
    target_id: targetId,
    depth: String(depth),
  });
  const dto = await apiGet<DependencyPathDto>(
    `${repositoryPath(projectId, repositoryId)}/graph/path?${params.toString()}`,
  );
  return {
    sourceId: dto.source_id,
    targetId: dto.target_id,
    found: dto.found,
    nodes: dto.nodes.map(toGraphNode),
    relationships: dto.relationships.map(toGraphRelationship),
    length: dto.length,
  };
}

export async function fetchGraphInsights(
  projectId: string,
  repositoryId: string,
  limit: number,
): Promise<GraphInsights> {
  const dto = await apiGet<GraphInsightsDto>(
    `${repositoryPath(projectId, repositoryId)}/graph/insights?limit=${limit}`,
  );
  return {
    repositoryId: dto.repository_id,
    mostConnectedFiles: dto.most_connected_files.map(toNodeDegree),
    dependencyHotspots: dto.dependency_hotspots.map(toNodeDegree),
    isolatedNodes: dto.isolated_nodes.map(toGraphNode),
    mutualImportPairs: dto.mutual_import_pairs.map((pair) => ({
      fileA: toGraphNode(pair.file_a),
      fileB: toGraphNode(pair.file_b),
    })),
    unresolvedDependencyCount: dto.unresolved_dependency_count,
    computedAt: dto.computed_at,
  };
}

export async function fetchGraphStatistics(
  projectId: string,
  repositoryId: string,
): Promise<GraphStatistics> {
  const dto = await apiGet<GraphStatisticsDto>(
    `${repositoryPath(projectId, repositoryId)}/graph/statistics`,
  );
  return {
    repositoryId: dto.repository_id,
    totalNodes: dto.total_nodes,
    totalFiles: dto.total_files,
    totalSymbols: dto.total_symbols,
    totalRelationships: dto.total_relationships,
    relationshipsByKind: dto.relationships_by_kind.map((entry) => ({
      kind: entry.kind,
      count: entry.count,
    })),
    highestInDegree: dto.highest_in_degree.map(toNodeDegree),
    highestOutDegree: dto.highest_out_degree.map(toNodeDegree),
    projectedAt: dto.projected_at,
    freshness: dto.freshness,
    computedAt: dto.computed_at,
  };
}
