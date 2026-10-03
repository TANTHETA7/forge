/**
 * AppShell component.
 *
 * Purpose:       The unified Forge Developer Intelligence Workspace shell.
 * Responsibility: Compose top navigation, sidebar, dynamic workspace view,
 *                 bottom status telemetry, and global command palette.
 * Architecture:   Desktop-first developer tool inspired by Sourcegraph, VS Code,
 *                 and Linear dark-first design principles.
 * Depends on:    presentation/shell/{TopBar,LeftSidebar,BottomStatusBar,CommandPalette},
 *                presentation/workspace/{WorkspaceContext,RepositoryDashboard,ExplorerWorkspace,GraphWorkspace,ImpactWorkspace,IntelligenceWorkspace},
 *                application/pipeline/useRepositoryPipeline.ts,
 *                application/explorer/useRepositoryExplorer.ts,
 *                application/graph/useRepositoryGraph.ts,
 *                application/rag/useRepositoryRag.ts.
 * Depended on by: App.tsx.
 */

import { useState } from "react";
import { useRepositoryPipeline } from "@/application/pipeline/useRepositoryPipeline";
import { useRepositoryExplorer } from "@/application/explorer/useRepositoryExplorer";
import { useRepositoryGraph } from "@/application/graph/useRepositoryGraph";
import { useRepositoryRag } from "@/application/rag/useRepositoryRag";
import {
  WorkspaceProvider,
  useWorkspace,
} from "@/presentation/workspace/WorkspaceContext";
import { TopBar } from "@/presentation/shell/TopBar";
import { LeftSidebar } from "@/presentation/shell/LeftSidebar";
import { BottomStatusBar } from "@/presentation/shell/BottomStatusBar";
import { CommandPalette } from "@/presentation/shell/CommandPalette";
import { RepositoryDashboard } from "@/presentation/workspace/RepositoryDashboard";
import { ExplorerWorkspace } from "@/presentation/workspace/ExplorerWorkspace";
import { GraphWorkspace } from "@/presentation/workspace/GraphWorkspace";
import { ImpactWorkspace } from "@/presentation/workspace/ImpactWorkspace";
import { IntelligenceWorkspace } from "@/presentation/workspace/IntelligenceWorkspace";
import type { GraphNode } from "@/domain/graph/types";

function WorkspaceView() {
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

  const { section } = useWorkspace();

  const isParsed = stageStates.parse === "done";
  const isProjected = stageStates.project === "done";

  const explorerState = useRepositoryExplorer(
    project?.id ?? null,
    repository?.id ?? null,
    isParsed,
  );

  const graphState = useRepositoryGraph(
    project?.id ?? null,
    repository?.id ?? null,
    isProjected,
  );

  const ragState = useRepositoryRag(
    project?.id ?? null,
    repository?.id ?? null,
    isParsed,
  );

  const [cachedGraphNodes, setCachedGraphNodes] = useState<GraphNode[]>([]);

  // Keep cached graph nodes updated when graph loads
  const handleNodesLoaded = (nodes: GraphNode[]) => {
    if (nodes.length > 0 && nodes.length !== cachedGraphNodes.length) {
      setCachedGraphNodes(nodes);
    }
  };

  const files = explorerState.files.data ?? [];
  const symbols = explorerState.symbols.data ?? [];
  const graphNodes =
    graphState.graph.nodes.length > 0 ? graphState.graph.nodes : cachedGraphNodes;

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-forge-bg text-forge-text-primary antialiased">
      {/* Top Application Bar */}
      <TopBar
        project={project}
        repository={repository}
        stageStates={stageStates}
        isIndexed={ragState.isIndexed}
      />

      {/* Main Workspace Frame */}
      <div className="flex flex-1 overflow-hidden">
        {/* Persistent Left Sidebar */}
        <LeftSidebar
          stageStates={stageStates}
          isBusy={isBusy}
          canRunRemaining={isBusy ? false : projectionAction.data === null && repository !== null}
          onRunRemaining={runRemaining}
          onReset={reset}
          fileCount={parseAction.data?.fileCount}
          symbolCount={parseAction.data?.symbolCount}
          nodeCount={projectionAction.data?.nodeCount}
          hasRepository={repository !== null}
        />

        {/* Dynamic Workspace Container */}
        <main className="flex-1 overflow-y-auto bg-forge-bg relative">
          {section === "overview" && (
            <RepositoryDashboard
              project={project}
              repository={repository}
              stageStates={stageStates}
              isBusy={isBusy}
              parse={parseAction.data}
              analysis={analyzeAction.data}
              projection={projectionAction.data}
              graphStats={graphState.statistics.data}
              insights={graphState.insights.data}
              indexStatus={ragState.status.data}
              isIndexed={ragState.isIndexed}
              importPending={importAction.isPending}
              importError={importAction.error}
              onImport={(name, src) => void importAction.run(name, src)}
              onRunParse={() => void parseAction.run()}
              onRunAnalyze={() => void analyzeAction.run()}
              onRunProject={() => void projectionAction.run()}
              onRunRemaining={runRemaining}
              onReset={reset}
              onTriggerIndex={() => void ragState.handleIndex()}
              indexPending={ragState.indexing.isPending}
            />
          )}

          {section === "explorer" && (
            <ExplorerWorkspace
              projectId={project?.id ?? null}
              repositoryId={repository?.id ?? null}
              enabled={isParsed}
              graphNodes={graphNodes}
            />
          )}

          {section === "graph" && (
            <GraphWorkspace
              projectId={project?.id ?? null}
              repositoryId={repository?.id ?? null}
              enabled={isProjected}
              onNodesLoaded={handleNodesLoaded}
            />
          )}

          {section === "impact" && (
            <ImpactWorkspace
              projectId={project?.id ?? null}
              repositoryId={repository?.id ?? null}
              enabled={isProjected}
              graphNodes={graphNodes}
            />
          )}

          {section === "intelligence" && (
            <IntelligenceWorkspace
              projectId={project?.id ?? null}
              repositoryId={repository?.id ?? null}
              enabled={isParsed}
            />
          )}
        </main>
      </div>

      {/* Persistent Bottom Status Dock */}
      <BottomStatusBar
        project={project}
        repository={repository}
        fileCount={parseAction.data?.fileCount}
        symbolCount={parseAction.data?.symbolCount}
        edgeCount={analyzeAction.data?.edgeCount}
        graphStats={graphState.statistics.data}
        isIndexed={ragState.isIndexed}
      />

      {/* Global Command Palette */}
      <CommandPalette
        files={files}
        symbols={symbols}
        canRunPipeline={!isBusy && projectionAction.data === null && repository !== null}
        onRunRemaining={runRemaining}
        onTriggerIndex={() => void ragState.handleIndex()}
      />
    </div>
  );
}

export function AppShell() {
  return (
    <WorkspaceProvider>
      <WorkspaceView />
    </WorkspaceProvider>
  );
}
