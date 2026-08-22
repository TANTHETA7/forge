/**
 * Pipeline domain types.
 *
 * Purpose:       Mirror the three analysis-summary wire contracts
 *                (`ParseSummaryResponse`, `DependencyAnalysisSummaryResponse`,
 *                `ProjectionSummaryResponse`) and name the pipeline's stages.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: The backend enforces an order — parse, then analyze-dependencies,
 *                then graph/project, answering 409 `UnsupportedRepositoryStateError`
 *                if called out of order. `PipelineStage` lets the UI reflect that
 *                order rather than rediscovering it from failed requests.
 * Depended on by: infrastructure/api/pipelineApi.ts,
 *                 application/pipeline/useRepositoryPipeline.ts,
 *                 presentation/pipeline/PipelineSteps.tsx.
 */

export interface ParseSummary {
  repositoryId: string;
  fileCount: number;
  symbolCount: number;
  importCount: number;
  errorCount: number;
  parsedAt: string;
}

export interface DependencyAnalysisSummary {
  repositoryId: string;
  edgeCount: number;
  resolvedCount: number;
  ambiguousCount: number;
  unresolvedCount: number;
  analyzedAt: string;
}

export interface ProjectionSummary {
  repositoryId: string;
  nodeCount: number;
  relationshipCount: number;
  projectedAt: string;
}

/**
 * The pipeline steps, in the order the backend requires them.
 *
 * `import` completes synchronously as part of the ZIP/Git upload, so it is
 * already done by the time a repository exists.
 */
export type PipelineStage = "import" | "parse" | "analyze" | "project";
