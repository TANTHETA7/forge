import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import { ImportForm } from "@/presentation/repository/ImportForm";
import { formatBytes, formatLanguages, formatTimestamp } from "@/presentation/shared/format";
import type { Repository } from "@/domain/repository/types";
import type { Project } from "@/domain/project/types";
import type {
  ImportSource,
  StageStates,
} from "@/application/pipeline/useRepositoryPipeline";
import type { ParseSummary } from "@/domain/pipeline/types";
import type { DependencyAnalysisSummary } from "@/domain/pipeline/types";
import type { ProjectionSummary } from "@/domain/pipeline/types";
import { graphNodeLabel, type GraphStatistics, type GraphInsights } from "@/domain/graph/types";
import type { IndexStatus } from "@/domain/rag/types";

interface RepositoryDashboardProps {
  project: Project | null;
  repository: Repository | null;
  stageStates: StageStates;
  isBusy: boolean;
  parse: ParseSummary | null;
  analysis: DependencyAnalysisSummary | null;
  projection: ProjectionSummary | null;
  graphStats: GraphStatistics | null;
  insights: GraphInsights | null;
  indexStatus: IndexStatus | null;
  isIndexed: boolean;
  importPending: boolean;
  importError: string | null;
  onImport: (name: string, source: ImportSource) => void;
  onRunParse: () => void;
  onRunAnalyze: () => void;
  onRunProject: () => void;
  onRunRemaining: () => void;
  onReset: () => void;
  onTriggerIndex: () => void;
  indexPending: boolean;
}

export function RepositoryDashboard({
  project,
  repository,
  stageStates,
  isBusy,
  parse,
  analysis,
  projection,
  graphStats,
  insights,
  indexStatus,
  isIndexed,
  importPending,
  importError,
  onImport,
  onRunParse,
  onRunAnalyze,
  onRunProject,
  onRunRemaining,
  onReset,
  onTriggerIndex,
  indexPending,
}: RepositoryDashboardProps) {
  const { navigateToExplorer, navigateToGraph, navigateToIntelligence } = useWorkspace();

  if (!repository) {
    return (
      <div className="relative min-h-[calc(100vh-85px)] overflow-hidden flex flex-col items-center justify-center p-6 forge-dot-grid">
        {/* Ambient glow - kept extremely subtle to maintain predominantly black background */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-forge-accent/[0.04] rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 w-full max-w-2xl text-center space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-forge-accent/30 bg-forge-accent/10 px-3 py-1 text-xs text-forge-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-forge-accent animate-pulse" />
            <span>FORGE DEVELOPER INTELLIGENCE</span>
          </div>

          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-forge-text-primary">
            The context layer for your entire codebase
          </h1>

          <p className="text-sm sm:text-base text-forge-text-secondary max-w-xl mx-auto leading-relaxed">
            Construct code property graphs, resolve multi-hop AST dependencies,
            and answer questions grounded strictly in your source code.
          </p>

          <div className="rounded-2xl border border-forge-border bg-forge-card p-6 text-left shadow-2xl backdrop-blur-sm">
            <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
              Import a repository to begin analysis
            </h2>
            <ImportForm
              isPending={importPending}
              error={importError}
              disabled={isBusy}
              onImport={onImport}
            />
          </div>
        </div>
      </div>
    );
  }

  const { metadata } = repository;
  const isParsed = stageStates.parse === "done";
  const isProjected = stageStates.project === "done";

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Repository Header Banner */}
      <div className="rounded-xl border border-forge-border bg-forge-card p-5 relative overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-xl font-bold text-forge-text-primary">
                {repository.displayName}
              </h1>
              <span className="rounded bg-forge-elevated border border-forge-border px-2 py-0.5 font-mono text-[10px] uppercase text-forge-text-secondary">
                {repository.sourceType}
              </span>
              <span className="rounded-full bg-emerald-950/80 border border-emerald-800 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
                {repository.status}
              </span>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-forge-text-muted">
              {project && (
                <span>
                  Project: <strong className="text-forge-text-secondary">{project.name}</strong>
                </span>
              )}
              <span>·</span>
              <span>Imported {formatTimestamp(repository.createdAt)}</span>
              {metadata && (
                <>
                  <span>·</span>
                  <span>{formatLanguages(metadata.languageStats)}</span>
                  <span>·</span>
                  <span>{formatBytes(metadata.totalSizeBytes)}</span>
                </>
              )}
            </div>
          </div>

          {/* Quick Action Navigation Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!isParsed}
              onClick={() => navigateToExplorer()}
              className="rounded-lg border border-forge-border bg-forge-elevated px-3 py-1.5 text-xs font-medium text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
            >
              Open Explorer →
            </button>
            <button
              type="button"
              disabled={!isProjected}
              onClick={() => navigateToGraph()}
              className="rounded-lg border border-forge-border bg-forge-elevated px-3 py-1.5 text-xs font-medium text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
            >
              Open Graph →
            </button>
            <button
              type="button"
              disabled={!isParsed}
              onClick={() => navigateToIntelligence()}
              className="rounded-lg bg-forge-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-forge-accent-hover transition disabled:opacity-40 shadow-sm"
            >
              Ask Forge AI
            </button>
          </div>
        </div>
      </div>

      {/* Top Telemetry Metric Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
        <div className="rounded-xl border border-forge-border bg-forge-panel p-4">
          <div className="text-[11px] uppercase tracking-wider text-forge-text-muted">
            Source Files
          </div>
          <div className="mt-1 text-2xl font-bold font-mono text-forge-text-primary">
            {parse?.fileCount ?? metadata?.fileCount ?? 0}
          </div>
          <div className="mt-1 text-[11px] text-forge-text-muted">
            {parse?.errorCount ? (
              <span className="text-red-400 font-medium">
                {parse.errorCount} syntax error(s)
              </span>
            ) : (
              <span className="text-emerald-400">All syntax clean</span>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-forge-border bg-forge-panel p-4">
          <div className="text-[11px] uppercase tracking-wider text-forge-text-muted">
            Code Symbols
          </div>
          <div className="mt-1 text-2xl font-bold font-mono text-forge-text-primary">
            {parse?.symbolCount ?? 0}
          </div>
          <div className="mt-1 text-[11px] text-forge-text-muted">
            {parse?.importCount ?? 0} file imports
          </div>
        </div>

        <div className="rounded-xl border border-forge-border bg-forge-panel p-4">
          <div className="text-[11px] uppercase tracking-wider text-forge-text-muted">
            Dependency Edges
          </div>
          <div className="mt-1 text-2xl font-bold font-mono text-forge-text-primary">
            {analysis?.edgeCount ?? 0}
          </div>
          <div className="mt-1 text-[11px] text-forge-text-muted">
            {analysis ? `${analysis.resolvedCount} resolved` : "Not analyzed"}
          </div>
        </div>

        <div className="rounded-xl border border-forge-border bg-forge-panel p-4">
          <div className="text-[11px] uppercase tracking-wider text-forge-text-muted">
            Neo4j Nodes
          </div>
          <div className="mt-1 text-2xl font-bold font-mono text-forge-text-primary">
            {graphStats?.totalNodes ?? projection?.nodeCount ?? 0}
          </div>
          <div className="mt-1 text-[11px] text-forge-text-muted">
            {graphStats?.totalRelationships ?? projection?.relationshipCount ?? 0} relationships
          </div>
        </div>

        <div className="rounded-xl border border-forge-border bg-forge-panel p-4 col-span-2 sm:col-span-1">
          <div className="text-[11px] uppercase tracking-wider text-forge-text-muted">
            AI Vectors
          </div>
          <div className="mt-1 text-2xl font-bold font-mono text-forge-text-primary">
            {indexStatus?.chunkCount ?? 0}
          </div>
          <div className="mt-1 text-[11px] text-forge-text-muted">
            {isIndexed ? (
              <span className="text-emerald-400">Indexed · Qwen 2.5</span>
            ) : (
              <span className="text-amber-400">Needs indexing</span>
            )}
          </div>
        </div>
      </div>

      {/* Pipeline Stages Execution Grid */}
      <div className="rounded-xl border border-forge-border bg-forge-card p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-forge-text-primary">
              Analysis Pipeline Lifecycle
            </h2>
            <p className="text-xs text-forge-text-muted">
              AST parsing → multi-hop dependency resolution → Neo4j projection → vector indexing
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRunRemaining}
              disabled={isBusy || projection !== null}
              className="rounded-lg bg-forge-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-forge-accent-hover transition disabled:opacity-40"
            >
              {isBusy ? "Running stages…" : "Run remaining stages"}
            </button>
            <button
              type="button"
              onClick={onReset}
              disabled={isBusy}
              className="rounded-lg border border-forge-border bg-forge-elevated px-3 py-1.5 text-xs text-forge-text-secondary hover:text-forge-text-primary transition disabled:opacity-40"
            >
              Start over
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          {/* Stage 1: Parse */}
          <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-forge-text-muted">01 · PARSE</span>
              <span
                className={`font-mono text-[10px] font-semibold uppercase ${
                  stageStates.parse === "ready" ? "text-emerald-400" : "text-neutral-500"
                }`}
              >
                {stageStates.parse}
              </span>
            </div>
            <div className="text-xs font-medium text-forge-text-primary">
              Tree-sitter Parser
            </div>
            <p className="text-[11px] text-forge-text-muted">
              Extracts files, function/class symbols, and imports into PostgreSQL.
            </p>
            {parse ? (
              <div className="pt-2 border-t border-forge-border text-[11px] font-mono text-forge-text-secondary">
                {parse.fileCount} files · {parse.symbolCount} symbols
              </div>
            ) : (
              <button
                type="button"
                onClick={onRunParse}
                disabled={isBusy}
                className="mt-2 w-full rounded border border-forge-border bg-forge-elevated py-1 text-xs text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
              >
                Run parse
              </button>
            )}
          </div>

          {/* Stage 2: Analyze */}
          <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-forge-text-muted">02 · ANALYZE</span>
              <span
                className={`font-mono text-[10px] font-semibold uppercase ${
                  stageStates.analyze === "ready" ? "text-emerald-400" : "text-neutral-500"
                }`}
              >
                {stageStates.analyze}
              </span>
            </div>
            <div className="text-xs font-medium text-forge-text-primary">
              Dependency Resolution
            </div>
            <p className="text-[11px] text-forge-text-muted">
              Resolves imports, function calls, and class inheritance.
            </p>
            {analysis ? (
              <div className="pt-2 border-t border-forge-border text-[11px] font-mono text-forge-text-secondary">
                {analysis.edgeCount} edges · {analysis.resolvedCount} resolved
              </div>
            ) : (
              <button
                type="button"
                onClick={onRunAnalyze}
                disabled={isBusy || !isParsed}
                className="mt-2 w-full rounded border border-forge-border bg-forge-elevated py-1 text-xs text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
              >
                Run analyze
              </button>
            )}
          </div>

          {/* Stage 3: Project */}
          <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-forge-text-muted">03 · GRAPH</span>
              <span
                className={`font-mono text-[10px] font-semibold uppercase ${
                  stageStates.project === "ready" ? "text-emerald-400" : "text-neutral-500"
                }`}
              >
                {stageStates.project}
              </span>
            </div>
            <div className="text-xs font-medium text-forge-text-primary">
              Neo4j Projection
            </div>
            <p className="text-[11px] text-forge-text-muted">
              Projects resolved dependencies into Neo4j graph nodes and relationships.
            </p>
            {projection ? (
              <div className="pt-2 border-t border-forge-border text-[11px] font-mono text-forge-text-secondary">
                {projection.nodeCount} nodes · {projection.relationshipCount} rels
              </div>
            ) : (
              <button
                type="button"
                onClick={onRunProject}
                disabled={isBusy || stageStates.analyze !== "ready"}
                className="mt-2 w-full rounded border border-forge-border bg-forge-elevated py-1 text-xs text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
              >
                Project graph
              </button>
            )}
          </div>

          {/* Stage 4: Index AI */}
          <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-forge-text-muted">04 · AI INDEX</span>
              <span
                className={`font-mono text-[10px] font-semibold uppercase ${
                  isIndexed ? "text-emerald-400" : "text-neutral-500"
                }`}
              >
                {isIndexed ? "ready" : "pending"}
              </span>
            </div>
            <div className="text-xs font-medium text-forge-text-primary">
              Vector Indexing
            </div>
            <p className="text-[11px] text-forge-text-muted">
              Generates 768-dim embeddings with nomic-embed-text for Qwen RAG.
            </p>
            {isIndexed ? (
              <div className="pt-2 border-t border-forge-border text-[11px] font-mono text-forge-text-secondary">
                {indexStatus?.chunkCount} chunks ready for code Q&amp;A
              </div>
            ) : (
              <button
                type="button"
                onClick={onTriggerIndex}
                disabled={isBusy || indexPending || !isParsed}
                className="mt-2 w-full rounded border border-forge-border bg-forge-elevated py-1 text-xs text-forge-text-primary hover:bg-forge-hover transition disabled:opacity-40"
              >
                {indexPending ? "Indexing…" : "Index repository"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Graph Insights & Structural Analysis */}
      {insights && (
        <div className="rounded-xl border border-forge-border bg-forge-card p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-forge-text-primary">
              Repository Graph Intelligence
            </h2>
            <p className="text-xs text-forge-text-muted">
              Deep topological metrics computed from the Neo4j knowledge graph
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {/* Most Connected Files */}
            <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted mb-2">
                Most Connected Files
              </h3>
              {insights.mostConnectedFiles.length === 0 ? (
                <p className="text-xs text-neutral-500">No file has any import edges.</p>
              ) : (
                <ul className="space-y-1.5">
                  {insights.mostConnectedFiles.slice(0, 5).map((entry) => (
                    <li
                      key={entry.node.id}
                      className="flex items-center justify-between text-xs font-mono"
                    >
                      <span className="truncate text-forge-text-secondary max-w-[180px]">
                        {graphNodeLabel(entry.node)}
                      </span>
                      <span className="rounded bg-forge-elevated px-1.5 py-0.5 text-forge-accent font-semibold">
                        {entry.degree}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Dependency Hotspots */}
            <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted mb-2">
                Dependency Hotspots
              </h3>
              {insights.dependencyHotspots.length === 0 ? (
                <p className="text-xs text-neutral-500">No symbol is entangled.</p>
              ) : (
                <ul className="space-y-1.5">
                  {insights.dependencyHotspots.slice(0, 5).map((entry) => (
                    <li
                      key={entry.node.id}
                      className="flex items-center justify-between text-xs font-mono"
                    >
                      <span className="truncate text-forge-text-secondary max-w-[180px]">
                        {graphNodeLabel(entry.node)}
                      </span>
                      <span className="rounded bg-forge-elevated px-1.5 py-0.5 text-purple-400 font-semibold">
                        {entry.degree}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Circular Dependencies / Mutual Imports */}
            <div className="rounded-lg border border-forge-border bg-forge-panel p-3.5">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted mb-2">
                Mutual Import Pairs
              </h3>
              {insights.mutualImportPairs.length === 0 ? (
                <div className="text-xs text-emerald-400/90 space-y-1">
                  <p>✓ No direct circular imports detected.</p>
                  <p className="text-[10px] text-forge-text-muted">
                    Clean unidirectional dependency hierarchy.
                  </p>
                </div>
              ) : (
                <ul className="space-y-1.5">
                  {insights.mutualImportPairs.slice(0, 3).map((pair, idx) => (
                    <li
                      key={idx}
                      className="text-[11px] font-mono text-amber-300 rounded bg-amber-950/40 border border-amber-900/40 p-1.5"
                    >
                      {graphNodeLabel(pair.fileA)} ⇄ {graphNodeLabel(pair.fileB)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
