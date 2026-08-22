/**
 * useRepositoryPipeline hook.
 *
 * Purpose:       Orchestrate the Phase 2 vertical slice end to end — create a
 *                project, import a repository into it, then run parse →
 *                analyze-dependencies → graph projection, exposing each stage as
 *                view-state.
 * Responsibility: React state management and stage sequencing — no fetch details
 *                 (those live in infrastructure), no rendering (presentation).
 * Why it exists: The backend enforces the pipeline order and answers 409
 *                `UnsupportedRepositoryStateError` when a stage is called early.
 *                Deriving each stage's `locked | ready | running | done | failed`
 *                state here lets the UI disable a step rather than let the user
 *                trigger a request that is guaranteed to fail. Every operation is
 *                synchronous server-side, so there is no polling here by design.
 * Depends on:    application/shared/useAsyncAction.ts, infrastructure/api/{project,
 *                repository,pipeline}Api.ts, domain/{project,repository,pipeline}/types.ts.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import { useCallback, useMemo, useState } from "react";

import { useAsyncAction } from "@/application/shared/useAsyncAction";
import { createProject } from "@/infrastructure/api/projectApi";
import {
  fetchRepository,
  importGitRepository,
  importZipRepository,
} from "@/infrastructure/api/repositoryApi";
import {
  analyzeDependencies,
  parseRepository,
  projectGraph,
} from "@/infrastructure/api/pipelineApi";
import type { Project } from "@/domain/project/types";
import type { Repository } from "@/domain/repository/types";
import type { PipelineStage } from "@/domain/pipeline/types";

/** How a repository is being brought in — one import stage, two possible sources. */
export type ImportSource =
  | { kind: "zip"; file: File; displayName?: string }
  | { kind: "git"; url: string };

export type StageState = "locked" | "ready" | "running" | "done" | "failed";

export function useRepositoryPipeline() {
  const [project, setProject] = useState<Project | null>(null);
  const [repository, setRepository] = useState<Repository | null>(null);

  const importAction = useAsyncAction(async (projectName: string, source: ImportSource) => {
    // The project must exist before anything can be imported into it, so this one
    // user action is two calls. Keeping the created project in state means a failed
    // import can be retried without creating a duplicate project.
    const created = project ?? (await createProject(projectName));
    setProject(created);

    const imported =
      source.kind === "zip"
        ? await importZipRepository(created.id, source.file, source.displayName)
        : await importGitRepository(created.id, source.url);

    setRepository(imported);
    return imported;
  });

  const requireIds = useCallback(() => {
    if (!project || !repository) {
      throw new Error("Import a repository before running this stage");
    }
    return { projectId: project.id, repositoryId: repository.id };
  }, [project, repository]);

  /**
   * Re-read the repository so the card shows persisted server state rather than the
   * import response. Deliberately non-fatal: a stage that genuinely succeeded must
   * not be reported as failed just because this follow-up read did.
   */
  const refreshRepository = useCallback(async (projectId: string, repositoryId: string) => {
    try {
      setRepository(await fetchRepository(projectId, repositoryId));
    } catch {
      // Keep the last known repository — the stage result still stands.
    }
  }, []);

  const parseAction = useAsyncAction(async () => {
    const { projectId, repositoryId } = requireIds();
    const summary = await parseRepository(projectId, repositoryId);
    await refreshRepository(projectId, repositoryId);
    return summary;
  });

  const analyzeAction = useAsyncAction(async () => {
    const { projectId, repositoryId } = requireIds();
    const summary = await analyzeDependencies(projectId, repositoryId);
    await refreshRepository(projectId, repositoryId);
    return summary;
  });

  const projectionAction = useAsyncAction(async () => {
    const { projectId, repositoryId } = requireIds();
    const summary = await projectGraph(projectId, repositoryId);
    await refreshRepository(projectId, repositoryId);
    return summary;
  });

  /** Run every stage the repository hasn't completed yet, stopping at the first failure. */
  const runRemaining = useCallback(async () => {
    const parsed = parseAction.data ?? (await parseAction.run());
    if (!parsed) return;

    const analyzed = analyzeAction.data ?? (await analyzeAction.run());
    if (!analyzed) return;

    if (!projectionAction.data) await projectionAction.run();
  }, [parseAction, analyzeAction, projectionAction]);

  const reset = useCallback(() => {
    setProject(null);
    setRepository(null);
    importAction.reset();
    parseAction.reset();
    analyzeAction.reset();
    projectionAction.reset();
  }, [importAction, parseAction, analyzeAction, projectionAction]);

  const stageStates = useMemo<Record<PipelineStage, StageState>>(() => {
    const derive = (
      unlocked: boolean,
      done: boolean,
      isPending: boolean,
      error: string | null,
    ): StageState => {
      if (!unlocked) return "locked";
      if (isPending) return "running";
      if (done) return "done";
      if (error) return "failed";
      return "ready";
    };

    return {
      import: derive(true, repository !== null, importAction.isPending, importAction.error),
      parse: derive(
        repository !== null,
        parseAction.data !== null,
        parseAction.isPending,
        parseAction.error,
      ),
      analyze: derive(
        parseAction.data !== null,
        analyzeAction.data !== null,
        analyzeAction.isPending,
        analyzeAction.error,
      ),
      project: derive(
        analyzeAction.data !== null,
        projectionAction.data !== null,
        projectionAction.isPending,
        projectionAction.error,
      ),
    };
  }, [repository, importAction, parseAction, analyzeAction, projectionAction]);

  const isBusy =
    importAction.isPending ||
    parseAction.isPending ||
    analyzeAction.isPending ||
    projectionAction.isPending;

  return {
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
  };
}
