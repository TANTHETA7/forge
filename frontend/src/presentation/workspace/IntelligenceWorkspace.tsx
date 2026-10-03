import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import { RagPanel } from "@/presentation/rag/RagPanel";

interface IntelligenceWorkspaceProps {
  projectId: string | null;
  repositoryId: string | null;
  enabled: boolean;
}

export function IntelligenceWorkspace({
  projectId,
  repositoryId,
  enabled,
}: IntelligenceWorkspaceProps) {
  const {
    prefilledPrompt,
    navigateToExplorer,
    navigateToGraph,
  } = useWorkspace();

  if (!enabled) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-forge-text-muted">
        <div>
          <p className="text-sm font-medium text-forge-text-secondary">
            Forge Intelligence is locked
          </p>
          <p className="mt-1 text-xs">
            Run the repository parse stage first to index source files and symbols.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Workspace Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-forge-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-forge-accent animate-pulse" />
            <h1 className="text-lg font-bold text-forge-text-primary">
              Forge Intelligence
            </h1>
          </div>
          <p className="text-xs text-forge-text-muted mt-0.5">
            Grounded code intelligence powered by Qwen 2.5 Coder and Nomic Embed vector retrieval
          </p>
        </div>
      </div>

      {/* Embedded Enhanced RAG Panel */}
      <RagPanel
        projectId={projectId}
        repositoryId={repositoryId}
        enabled={enabled}
        initialQuestion={prefilledPrompt}
        onNavigateToFile={(path) => navigateToExplorer(path, null)}
        onNavigateToSymbol={(sym) => navigateToExplorer(null, sym)}
        onNavigateToGraph={(target) => navigateToGraph(target)}
      />
    </div>
  );
}
