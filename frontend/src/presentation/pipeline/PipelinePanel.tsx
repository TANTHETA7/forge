/**
 * PipelinePanel component.
 *
 * Purpose:       The Phase 2 vertical slice as one screen — create a project and
 *                import a repository, then run parse → dependency analysis → graph
 *                projection, showing each stage's real result.
 * Responsibility: Composition and rendering only. All sequencing, gating, and
 *                 error handling comes from `useRepositoryPipeline`.
 * Why it exists: Gives the pipeline a single coherent place in the UI, so the user
 *                can see at a glance which stages are done and which is next.
 * Depends on:    application/pipeline/useRepositoryPipeline.ts,
 *                presentation/repository/{ImportForm,RepositoryCard},
 *                presentation/pipeline/StageCard.tsx, presentation/shared/SummaryStat.tsx.
 * Depended on by: presentation/shell/AppShell.tsx.
 */

import { useRepositoryPipeline } from "@/application/pipeline/useRepositoryPipeline";
import { ExplorerPanel } from "@/presentation/explorer/ExplorerPanel";
import { GraphPanel } from "@/presentation/graph/GraphPanel";
import { ImportForm } from "@/presentation/repository/ImportForm";
import { RepositoryCard } from "@/presentation/repository/RepositoryCard";
import { StageCard } from "@/presentation/pipeline/StageCard";
import { SummaryStat } from "@/presentation/shared/SummaryStat";

const SECTION_CLASS = "rounded-lg border border-neutral-800 bg-neutral-900/40 p-4";

export function PipelinePanel() {
  const {
    project,
    repository,
    importAction,
    parseAction,
    analyzeAction,
    projectionAction,
    stageStates,
    isBusy,
    runRemaining,
    reset,
  } = useRepositoryPipeline();

  const parse = parseAction.data;
  const analysis = analyzeAction.data;
  const projection = projectionAction.data;

  return (
    <div className="space-y-4">
      <section className={SECTION_CLASS}>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-neutral-400">
          1 · Project &amp; repository
        </h2>

        {repository ? (
          <div className="space-y-3">
            {project && (
              <p className="text-sm text-neutral-400">
                Project <span className="text-neutral-100">{project.name}</span>{" "}
                <code className="text-xs text-neutral-500">{project.id}</code>
              </p>
            )}
            <RepositoryCard repository={repository} />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={runRemaining}
                disabled={isBusy || projection !== null}
                className={
                  "rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white " +
                  "hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-neutral-800 " +
                  "disabled:text-neutral-500"
                }
              >
                {isBusy ? "Running…" : "Run remaining stages"}
              </button>
              <button
                type="button"
                onClick={reset}
                disabled={isBusy}
                className={
                  "rounded-md bg-neutral-800 px-3 py-1.5 text-sm text-neutral-300 " +
                  "hover:bg-neutral-700 disabled:opacity-50"
                }
              >
                Start over
              </button>
            </div>
          </div>
        ) : (
          <ImportForm
            isPending={importAction.isPending}
            error={importAction.error}
            disabled={isBusy}
            onImport={(name, source) => void importAction.run(name, source)}
          />
        )}
      </section>

      <StageCard
        step={2}
        title="Parse repository"
        description="Tree-sitter parse into files, symbols, and imports."
        state={stageStates.parse}
        error={parseAction.error}
        runLabel="Parse"
        onRun={() => void parseAction.run()}
      >
        {parse && (
          <>
            <SummaryStat label="Files" value={parse.fileCount} />
            <SummaryStat label="Symbols" value={parse.symbolCount} />
            <SummaryStat label="Imports" value={parse.importCount} />
            <SummaryStat
              label="Parse errors"
              value={parse.errorCount}
              tone={parse.errorCount > 0 ? "bad" : "default"}
            />
          </>
        )}
      </StageCard>

      <StageCard
        step={3}
        title="Analyze dependencies"
        description="Resolve imports, calls, and inheritance into dependency edges."
        state={stageStates.analyze}
        error={analyzeAction.error}
        runLabel="Analyze"
        onRun={() => void analyzeAction.run()}
      >
        {analysis && (
          <>
            <SummaryStat label="Edges" value={analysis.edgeCount} />
            <SummaryStat label="Resolved" value={analysis.resolvedCount} />
            <SummaryStat
              label="Ambiguous"
              value={analysis.ambiguousCount}
              tone={analysis.ambiguousCount > 0 ? "warn" : "default"}
            />
            <SummaryStat
              label="Unresolved"
              value={analysis.unresolvedCount}
              tone={analysis.unresolvedCount > 0 ? "warn" : "default"}
            />
          </>
        )}
      </StageCard>

      <StageCard
        step={4}
        title="Project graph"
        description="Project the resolved dependencies into Neo4j as nodes and relationships."
        state={stageStates.project}
        error={projectionAction.error}
        runLabel="Project graph"
        onRun={() => void projectionAction.run()}
      >
        {projection && (
          <>
            <SummaryStat label="Nodes" value={projection.nodeCount} />
            <SummaryStat label="Relationships" value={projection.relationshipCount} />
          </>
        )}
      </StageCard>

      {projection && (
        <p className="rounded-lg bg-emerald-950 px-4 py-3 text-sm text-emerald-300">
          Pipeline complete — {projection.nodeCount} nodes and {projection.relationshipCount}{" "}
          relationships are queryable in Neo4j. Graph browsing and impact analysis are exposed by
          the backend but have no UI yet.
        </p>
      )}

      {/* Read-only exploration of what parsing produced. Appears once parse succeeds,
          which is the point at which /files, /symbols, and /parse-errors have data. */}
      <ExplorerPanel
        projectId={project?.id ?? null}
        repositoryId={repository?.id ?? null}
        enabled={parse !== null}
      />

      {/* The graph lives in Neo4j, so it is only queryable once projection succeeded.
          Before that the panel renders a locked state and issues no requests. */}
      <GraphPanel
        projectId={project?.id ?? null}
        repositoryId={repository?.id ?? null}
        enabled={projection !== null}
      />
    </div>
  );
}
