/**
 * Pipeline API client.
 *
 * Purpose:       Trigger the three analysis stages — parse, dependency analysis,
 *                graph projection — and translate their summary responses into
 *                domain types.
 * Responsibility: Three endpoints, each a single POST with no request body.
 * Why it exists: All three are synchronous on the backend and answer 201 with a
 *                summary (verified live: parse ~0.5s, analyze ~0.5s, projection
 *                ~8.4s on a first projection). They must be called in order —
 *                calling out of order answers 409 `UnsupportedRepositoryStateError`.
 * Depends on:    infrastructure/api/client.ts, wire.ts, domain/pipeline/types.ts.
 * Depended on by: application/pipeline/useRepositoryPipeline.ts.
 */

import { apiPost } from "@/infrastructure/api/client";
import { repositoryPath } from "@/infrastructure/api/wire";
import type {
  DependencyAnalysisSummary,
  ParseSummary,
  ProjectionSummary,
} from "@/domain/pipeline/types";

interface ParseSummaryDto {
  repository_id: string;
  file_count: number;
  symbol_count: number;
  import_count: number;
  error_count: number;
  parsed_at: string;
}

interface DependencySummaryDto {
  repository_id: string;
  edge_count: number;
  resolved_count: number;
  ambiguous_count: number;
  unresolved_count: number;
  analyzed_at: string;
}

interface ProjectionSummaryDto {
  repository_id: string;
  node_count: number;
  relationship_count: number;
  projected_at: string;
}

export async function parseRepository(
  projectId: string,
  repositoryId: string,
): Promise<ParseSummary> {
  const dto = await apiPost<ParseSummaryDto>(`${repositoryPath(projectId, repositoryId)}/parse`);
  return {
    repositoryId: dto.repository_id,
    fileCount: dto.file_count,
    symbolCount: dto.symbol_count,
    importCount: dto.import_count,
    errorCount: dto.error_count,
    parsedAt: dto.parsed_at,
  };
}

export async function analyzeDependencies(
  projectId: string,
  repositoryId: string,
): Promise<DependencyAnalysisSummary> {
  const dto = await apiPost<DependencySummaryDto>(
    `${repositoryPath(projectId, repositoryId)}/analyze-dependencies`,
  );
  return {
    repositoryId: dto.repository_id,
    edgeCount: dto.edge_count,
    resolvedCount: dto.resolved_count,
    ambiguousCount: dto.ambiguous_count,
    unresolvedCount: dto.unresolved_count,
    analyzedAt: dto.analyzed_at,
  };
}

export async function projectGraph(
  projectId: string,
  repositoryId: string,
): Promise<ProjectionSummary> {
  const dto = await apiPost<ProjectionSummaryDto>(
    `${repositoryPath(projectId, repositoryId)}/graph/project`,
  );
  return {
    repositoryId: dto.repository_id,
    nodeCount: dto.node_count,
    relationshipCount: dto.relationship_count,
    projectedAt: dto.projected_at,
  };
}
