import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import type { Project } from "@/domain/project/types";
import type { Repository } from "@/domain/repository/types";
import type { GraphStatistics } from "@/domain/graph/types";

interface BottomStatusBarProps {
  project: Project | null;
  repository: Repository | null;
  fileCount?: number;
  symbolCount?: number;
  edgeCount?: number;
  graphStats?: GraphStatistics | null;
  isIndexed?: boolean;
}

export function BottomStatusBar({
  project,
  repository,
  fileCount,
  symbolCount,
  edgeCount,
  graphStats,
  isIndexed,
}: BottomStatusBarProps) {
  const { section, setCommandPaletteOpen } = useWorkspace();

  return (
    <footer className="h-7 border-t border-[#181818] bg-[#060606] px-3 flex items-center justify-between text-[11px] text-forge-text-muted select-none flex-shrink-0 z-30">
      {/* Left: Scoped project and repository */}
      <div className="flex items-center gap-3">
        {project && repository ? (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 font-mono text-[10px] text-forge-text-secondary">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>{repository.displayName}</span>
            </span>
            <span className="text-forge-text-muted">/</span>
            <span className="font-mono text-[10px] text-forge-text-muted">
              {project.name}
            </span>
          </div>
        ) : (
          <span className="text-forge-text-muted">No repository active</span>
        )}
      </div>

      {/* Center: Live repository telemetry */}
      <div className="hidden md:flex items-center gap-3 font-mono text-[10px]">
        {fileCount !== undefined && (
          <span>
            <strong className="text-forge-text-primary">{fileCount}</strong> files
          </span>
        )}
        {symbolCount !== undefined && (
          <span>
            <strong className="text-forge-text-primary">{symbolCount}</strong> symbols
          </span>
        )}
        {edgeCount !== undefined && (
          <span>
            <strong className="text-forge-text-primary">{edgeCount}</strong> edges
          </span>
        )}
        {graphStats && (
          <span>
            <strong className="text-forge-text-primary">{graphStats.totalNodes}</strong> nodes ·{" "}
            <strong className="text-forge-text-primary">{graphStats.totalRelationships}</strong>{" "}
            rels
          </span>
        )}
        <span>
          AI:{" "}
          <strong
            className={isIndexed ? "text-emerald-400" : "text-amber-400"}
          >
            {isIndexed ? "Indexed" : "Pending"}
          </strong>
        </span>
      </div>

      {/* Right: Active Section & Shortcut hint */}
      <div className="flex items-center gap-3">
        <span className="uppercase tracking-wider font-semibold text-[9px] text-forge-accent">
          {section}
        </span>
        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="flex items-center gap-1 hover:text-forge-text-secondary transition"
        >
          <span>Command</span>
          <kbd className="rounded border border-forge-border bg-forge-card px-1 text-[9px] font-mono">
            ⌘K
          </kbd>
        </button>
      </div>
    </footer>
  );
}
