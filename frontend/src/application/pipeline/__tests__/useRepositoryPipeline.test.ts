import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRepositoryPipeline } from "@/application/pipeline/useRepositoryPipeline";
import * as projectApi from "@/infrastructure/api/projectApi";
import * as repositoryApi from "@/infrastructure/api/repositoryApi";
import * as pipelineApi from "@/infrastructure/api/pipelineApi";
import type { Project } from "@/domain/project/types";
import type { Repository } from "@/domain/repository/types";

const PROJECT: Project = {
  id: "p1",
  name: "demo",
  description: null,
  status: "created",
  createdAt: "2026-08-21T12:00:00Z",
  updatedAt: "2026-08-21T12:00:00Z",
};

const REPOSITORY: Repository = {
  id: "r1",
  projectId: "p1",
  sourceType: "zip",
  displayName: "tinyrepo",
  status: "ready",
  metadata: {
    fileCount: 3,
    directoryCount: 1,
    totalSizeBytes: 267,
    languageStats: { Python: 100 },
    hasReadme: false,
    hasGit: false,
    scannedAt: "2026-08-21T12:00:00Z",
  },
  errorMessage: null,
  createdAt: "2026-08-21T12:00:00Z",
  updatedAt: "2026-08-21T12:00:00Z",
};

const PARSE = {
  repositoryId: "r1",
  fileCount: 3,
  symbolCount: 6,
  importCount: 2,
  errorCount: 0,
  parsedAt: "2026-08-21T12:00:01Z",
};

const ANALYSIS = {
  repositoryId: "r1",
  edgeCount: 6,
  resolvedCount: 5,
  ambiguousCount: 0,
  unresolvedCount: 1,
  analyzedAt: "2026-08-21T12:00:02Z",
};

const PROJECTION = {
  repositoryId: "r1",
  nodeCount: 10,
  relationshipCount: 16,
  projectedAt: "2026-08-21T12:00:10Z",
};

const zipFile = () => new File(["x"], "tinyrepo.zip");

async function importRepository(result: { current: ReturnType<typeof useRepositoryPipeline> }) {
  await act(async () => {
    await result.current.importAction.run("demo", { kind: "zip", file: zipFile() });
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(projectApi, "createProject").mockResolvedValue(PROJECT);
  vi.spyOn(repositoryApi, "importZipRepository").mockResolvedValue(REPOSITORY);
  vi.spyOn(repositoryApi, "fetchRepository").mockResolvedValue(REPOSITORY);
  vi.spyOn(pipelineApi, "parseRepository").mockResolvedValue(PARSE);
  vi.spyOn(pipelineApi, "analyzeDependencies").mockResolvedValue(ANALYSIS);
  vi.spyOn(pipelineApi, "projectGraph").mockResolvedValue(PROJECTION);
});

describe("useRepositoryPipeline stage gating", () => {
  it("locks every analysis stage until a repository exists", () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    expect(result.current.stageStates).toEqual({
      import: "ready",
      parse: "locked",
      analyze: "locked",
      project: "locked",
    });
  });

  it("unlocks each stage only once the previous one succeeds", async () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    expect(result.current.stageStates).toMatchObject({
      import: "done",
      parse: "ready",
      analyze: "locked",
      project: "locked",
    });

    await act(async () => {
      await result.current.parseAction.run();
    });
    expect(result.current.stageStates).toMatchObject({ parse: "done", analyze: "ready" });

    await act(async () => {
      await result.current.analyzeAction.run();
    });
    expect(result.current.stageStates).toMatchObject({ analyze: "done", project: "ready" });

    await act(async () => {
      await result.current.projectionAction.run();
    });
    expect(result.current.stageStates.project).toBe("done");
  });
});

describe("useRepositoryPipeline data flow", () => {
  it("creates the project then imports into it, exposing both", async () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);

    expect(projectApi.createProject).toHaveBeenCalledWith("demo");
    expect(repositoryApi.importZipRepository).toHaveBeenCalledWith("p1", expect.any(File), undefined);
    expect(result.current.project).toEqual(PROJECT);
    expect(result.current.repository).toEqual(REPOSITORY);
  });

  it("passes the repository's real ids to each analysis stage", async () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await act(async () => {
      await result.current.parseAction.run();
    });

    expect(pipelineApi.parseRepository).toHaveBeenCalledWith("p1", "r1");
    expect(result.current.parseAction.data).toEqual(PARSE);
  });

  it("runs every remaining stage in order", async () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await act(async () => {
      await result.current.runRemaining();
    });

    expect(result.current.parseAction.data).toEqual(PARSE);
    expect(result.current.analyzeAction.data).toEqual(ANALYSIS);
    expect(result.current.projectionAction.data).toEqual(PROJECTION);
  });

  it("stops the run at the first failing stage", async () => {
    vi.spyOn(pipelineApi, "parseRepository").mockRejectedValue(new Error("parse exploded"));
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await act(async () => {
      await result.current.runRemaining();
    });

    expect(result.current.parseAction.error).toBe("parse exploded");
    expect(pipelineApi.analyzeDependencies).not.toHaveBeenCalled();
    expect(pipelineApi.projectGraph).not.toHaveBeenCalled();
    expect(result.current.stageStates).toMatchObject({ parse: "failed", analyze: "locked" });
  });
});

describe("useRepositoryPipeline repository refresh", () => {
  it("re-reads the repository after each stage so the card shows persisted state", async () => {
    const refreshed = { ...REPOSITORY, updatedAt: "2026-08-21T12:00:30Z" };
    vi.spyOn(repositoryApi, "fetchRepository").mockResolvedValue(refreshed);
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    expect(repositoryApi.fetchRepository).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.runRemaining();
    });

    expect(repositoryApi.fetchRepository).toHaveBeenCalledTimes(3);
    expect(repositoryApi.fetchRepository).toHaveBeenCalledWith("p1", "r1");
    expect(result.current.repository).toEqual(refreshed);
  });

  it("keeps a stage successful when only the follow-up refresh fails", async () => {
    vi.spyOn(repositoryApi, "fetchRepository").mockRejectedValue(new Error("refresh failed"));
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await act(async () => {
      await result.current.parseAction.run();
    });

    expect(result.current.parseAction.data).toEqual(PARSE);
    expect(result.current.parseAction.error).toBeNull();
    expect(result.current.stageStates.parse).toBe("done");
    // The pre-refresh repository is retained rather than cleared.
    expect(result.current.repository).toEqual(REPOSITORY);
  });
});

describe("useRepositoryPipeline error handling", () => {
  it("surfaces the backend's message when the import fails and leaves stages locked", async () => {
    vi.spyOn(repositoryApi, "importZipRepository").mockRejectedValue(
      new Error("File is not a valid ZIP archive"),
    );
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);

    await waitFor(() =>
      expect(result.current.importAction.error).toBe("File is not a valid ZIP archive"),
    );
    expect(result.current.repository).toBeNull();
    expect(result.current.stageStates).toMatchObject({ import: "failed", parse: "locked" });
  });

  it("does not create a second project when a failed import is retried", async () => {
    vi.spyOn(repositoryApi, "importZipRepository").mockRejectedValueOnce(
      new Error("File is not a valid ZIP archive"),
    );
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await importRepository(result);

    expect(projectApi.createProject).toHaveBeenCalledTimes(1);
    expect(result.current.repository).toEqual(REPOSITORY);
  });

  it("clears every stage on reset", async () => {
    const { result } = renderHook(() => useRepositoryPipeline());

    await importRepository(result);
    await act(async () => {
      await result.current.runRemaining();
    });
    act(() => {
      result.current.reset();
    });

    expect(result.current.project).toBeNull();
    expect(result.current.repository).toBeNull();
    expect(result.current.parseAction.data).toBeNull();
    expect(result.current.stageStates).toEqual({
      import: "ready",
      parse: "locked",
      analyze: "locked",
      project: "locked",
    });
  });
});
