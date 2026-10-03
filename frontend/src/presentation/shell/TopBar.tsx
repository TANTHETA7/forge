import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import { StatusBadge } from "@/presentation/shell/StatusBadge";
import type { Project } from "@/domain/project/types";
import type { Repository } from "@/domain/repository/types";
import type { StageState, StageStates } from "@/application/pipeline/useRepositoryPipeline";

interface TopBarProps {
  project: Project | null;
  repository: Repository | null;
  stageStates: StageStates;
  isIndexed?: boolean;
}

export function TopBar({
  project,
  repository,
  stageStates,
  isIndexed,
}: TopBarProps) {
  const { setCommandPaletteOpen, navigateToIntelligence } = useWorkspace();

  return (
    <header className="sticky top-0 z-40 flex h-14 w-full items-center justify-between border-b border-[#181818] bg-[#060606] px-4 backdrop-blur-md">
      {/* Left: Brand & Active Repository Selector */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          {/* Flame / Graph Icon */}
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-forge-accent/15 border border-forge-accent/30 text-forge-accent shadow-[0_0_12px_rgba(249,115,22,0.25)]">
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polygon points="12 2 19 21 12 17 5 21 12 2" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-semibold text-sm tracking-tight text-forge-text-primary">
                FORGE
              </span>
              <span className="rounded bg-forge-elevated border border-forge-border px-1.5 py-0.2 font-mono text-[9px] uppercase tracking-wider text-forge-text-muted">
                WORKSPACE
              </span>
            </div>
          </div>
        </div>

        <div className="h-4 w-[1px] bg-forge-border" />

        {/* Repository / Project Context Pill */}
        {repository ? (
          <div className="flex items-center gap-2 rounded-md border border-forge-border bg-forge-panel px-2.5 py-1 text-xs">
            <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />
            <span className="font-medium text-forge-text-primary">
              {repository.displayName}
            </span>
            <span className="font-mono text-[10px] text-forge-text-muted uppercase">
              {repository.sourceType}
            </span>
            {project && (
              <span className="text-[11px] text-forge-text-muted border-l border-forge-border pl-2">
                {project.name}
              </span>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-md border border-dashed border-forge-border px-2.5 py-1 text-xs text-forge-text-muted">
            <span className="h-2 w-2 rounded-full bg-neutral-600" />
            <span>No repository loaded</span>
          </div>
        )}
      </div>

      {/* Center: Command Palette Trigger */}
      <div className="flex-1 max-w-md mx-4">
        <button
          type="button"
          data-testid="command-palette-trigger"
          onClick={() => setCommandPaletteOpen(true)}
          className="flex w-full items-center justify-between rounded-lg border border-forge-border bg-[#0b0b0b] px-3 py-1.5 text-xs text-forge-text-muted transition hover:border-[#262626] hover:text-forge-text-secondary hover:bg-forge-elevated"
        >
          <div className="flex items-center gap-2">
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <span>Search files, symbols, commands...</span>
          </div>
          <kbd className="rounded border border-forge-border bg-forge-card px-1.5 py-0.5 font-mono text-[10px] text-forge-text-muted">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Right: Pipeline Stage Badges & Backend Health */}
      <div className="flex items-center gap-3">
        {/* Pipeline indicators */}
        <div className="hidden lg:flex items-center gap-1.5 text-xs">
          <StagePill label="Parse" state={stageStates.parse} />
          <span className="text-forge-text-muted text-[10px]">→</span>
          <StagePill label="Analyze" state={stageStates.analyze} />
          <span className="text-forge-text-muted text-[10px]">→</span>
          <StagePill label="Graph" state={stageStates.project} />
          <span className="text-forge-text-muted text-[10px]">→</span>
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-medium border ${
              isIndexed
                ? "bg-emerald-950/80 text-emerald-300 border-emerald-800/80"
                : "bg-forge-panel text-forge-text-muted border-forge-border"
            }`}
          >
            AI {isIndexed ? "✓" : "○"}
          </span>
        </div>

        <div className="h-4 w-[1px] bg-forge-border hidden sm:block" />

        {/* Quick Ask Forge action */}
        <button
          type="button"
          onClick={() => navigateToIntelligence()}
          className="hidden sm:flex items-center gap-1.5 rounded-md border border-forge-accent/30 bg-forge-accent/10 px-2.5 py-1 text-xs font-medium text-forge-accent hover:bg-forge-accent/20 transition"
        >
          <svg className="h-3 w-3" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
          </svg>
          <span>Ask Forge</span>
        </button>

        {/* StatusBadge for backend health */}
        <div className="scale-90">
          <StatusBadge />
        </div>
      </div>
    </header>
  );
}

function StagePill({
  label,
  state,
}: {
  label: string;
  state: StageState;
}) {
  const isDone = state === "done";
  const isRunning = state === "running";
  const isFailed = state === "failed";

  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-medium border ${
        isDone
          ? "bg-emerald-950/80 text-emerald-300 border-emerald-800/80"
          : isRunning
            ? "bg-amber-950/80 text-amber-300 border-amber-800/80 animate-pulse"
            : isFailed
              ? "bg-red-950/80 text-red-300 border-red-800/80"
              : "bg-forge-panel text-forge-text-muted border-forge-border"
      }`}
    >
      {label} {isDone ? "✓" : isRunning ? "…" : isFailed ? "✕" : "○"}
    </span>
  );
}
