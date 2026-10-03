import { useEffect } from "react";
import { useWorkspace, type WorkspaceSection } from "@/presentation/workspace/WorkspaceContext";
import type { StageState, StageStates } from "@/application/pipeline/useRepositoryPipeline";

interface LeftSidebarProps {
  stageStates: StageStates;
  isBusy: boolean;
  canRunRemaining: boolean;
  onRunRemaining: () => void;
  onReset: () => void;
  fileCount?: number;
  symbolCount?: number;
  nodeCount?: number;
  hasRepository: boolean;
}

export function LeftSidebar({
  stageStates,
  isBusy,
  canRunRemaining,
  onRunRemaining,
  onReset,
  fileCount,
  nodeCount,
  hasRepository,
}: LeftSidebarProps) {
  const { section, setSection } = useWorkspace();

  const isParsed = stageStates.parse === "done";
  const isProjected = stageStates.project === "done";

  // Number key shortcuts 1-5 to switch sections
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input or textarea
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.metaKey ||
        e.ctrlKey
      ) {
        return;
      }

      if (e.key === "1") setSection("overview");
      else if (e.key === "2" && isParsed) setSection("explorer");
      else if (e.key === "3" && isProjected) setSection("graph");
      else if (e.key === "4" && isProjected) setSection("impact");
      else if (e.key === "5" && isParsed) setSection("intelligence");
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setSection, isParsed, isProjected]);

  const navItems: {
    id: WorkspaceSection;
    label: string;
    shortcut: string;
    enabled: boolean;
    badge?: string | number;
    icon: (active: boolean) => React.ReactNode;
  }[] = [
    {
      id: "overview",
      label: "Overview",
      shortcut: "1",
      enabled: true,
      icon: (active) => (
        <svg
          className={`h-4 w-4 ${active ? "text-forge-accent" : "text-forge-text-muted"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
        </svg>
      ),
    },
    {
      id: "explorer",
      label: "Explorer",
      shortcut: "2",
      enabled: isParsed,
      badge: fileCount !== undefined ? `${fileCount}f` : undefined,
      icon: (active) => (
        <svg
          className={`h-4 w-4 ${active ? "text-forge-accent" : "text-forge-text-muted"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
          <path d="M2 10h20" />
        </svg>
      ),
    },
    {
      id: "graph",
      label: "Repository Graph",
      shortcut: "3",
      enabled: isProjected,
      badge: nodeCount !== undefined ? `${nodeCount}n` : undefined,
      icon: (active) => (
        <svg
          className={`h-4 w-4 ${active ? "text-forge-accent" : "text-forge-text-muted"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="6" cy="6" r="3" />
          <circle cx="18" cy="6" r="3" />
          <circle cx="12" cy="18" r="3" />
          <path d="M8.5 7.5l7 0" />
          <path d="M7.5 8.5l3.5 7" />
          <path d="M16.5 8.5l-3.5 7" />
        </svg>
      ),
    },
    {
      id: "impact",
      label: "Impact Analysis",
      shortcut: "4",
      enabled: isProjected,
      icon: (active) => (
        <svg
          className={`h-4 w-4 ${active ? "text-forge-accent" : "text-forge-text-muted"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
      ),
    },
    {
      id: "intelligence",
      label: "Forge Intelligence",
      shortcut: "5",
      enabled: isParsed,
      badge: "AI",
      icon: (active) => (
        <svg
          className={`h-4 w-4 ${active ? "text-forge-accent" : "text-forge-text-muted"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
        </svg>
      ),
    },
  ];

  return (
    <aside className="w-64 flex-shrink-0 border-r border-[#1a1a1a] bg-forge-sidebar flex flex-col justify-between select-none">
      {/* Top: Navigation list */}
      <div className="p-3 space-y-6">
        <div>
          <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-forge-text-muted">
            Workspace
          </div>
          <nav className="space-y-1">
            {navItems.map((item) => {
              const active = section === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  disabled={!item.enabled}
                  onClick={() => setSection(item.id)}
                  className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-medium transition ${
                    active
                      ? "bg-forge-elevated text-forge-text-primary ring-1 ring-forge-border shadow-sm"
                      : item.enabled
                        ? "text-forge-text-secondary hover:bg-forge-hover hover:text-forge-text-primary"
                        : "text-neutral-600 cursor-not-allowed opacity-50"
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    {item.icon(active)}
                    <span>{item.label}</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {item.badge && (
                      <span
                        className={`rounded px-1.5 py-0.2 font-mono text-[9px] font-semibold uppercase ${
                          item.badge === "AI"
                            ? "bg-forge-accent/20 text-forge-accent"
                            : "bg-forge-panel text-forge-text-muted border border-forge-border"
                        }`}
                      >
                        {item.badge}
                      </span>
                    )}
                    <kbd className="rounded border border-forge-border bg-forge-bg px-1 font-mono text-[9px] text-forge-text-muted">
                      {item.shortcut}
                    </kbd>
                  </div>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Pipeline Stage Tracker */}
        {hasRepository && (
          <div className="rounded-xl border border-forge-border bg-forge-panel/70 p-3 space-y-2.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-forge-text-secondary">
              <span>Pipeline Stages</span>
              <span className="font-mono text-[10px] text-forge-text-muted">
                {isProjected ? "Ready" : isBusy ? "Running…" : "Active"}
              </span>
            </div>

            <div className="space-y-1.5 text-xs">
              <StageRow label="Parse" state={stageStates.parse} />
              <StageRow label="Analyze" state={stageStates.analyze} />
              <StageRow label="Project" state={stageStates.project} />
            </div>

            {canRunRemaining && (
              <button
                type="button"
                onClick={onRunRemaining}
                disabled={isBusy}
                className="mt-2 w-full rounded-md bg-forge-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-forge-accent-hover transition disabled:opacity-50"
              >
                {isBusy ? "Running stages…" : "Run remaining stages"}
              </button>
            )}

            <button
              type="button"
              onClick={onReset}
              disabled={isBusy}
              className="w-full rounded-md border border-forge-border bg-forge-card px-2 py-1 text-[11px] text-forge-text-muted hover:text-forge-text-secondary transition disabled:opacity-50"
            >
              Start over
            </button>
          </div>
        )}
      </div>

      {/* Bottom Footer: System info */}
      <div className="p-3 border-t border-forge-border bg-forge-sidebar/60 text-[11px] text-forge-text-muted flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <span>Forge Graph v0.1.0</span>
        </span>
        <span className="font-mono text-[10px]">Neo4j · Ollama</span>
      </div>
    </aside>
  );
}

function StageRow({
  label,
  state,
}: {
  label: string;
  state: StageState;
}) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-forge-text-muted">{label}</span>
      <span
        className={`font-mono text-[10px] font-medium ${
          state === "done"
            ? "text-emerald-400"
            : state === "running"
              ? "text-amber-400 animate-pulse"
              : state === "failed"
                ? "text-red-400"
                : state === "ready"
                  ? "text-forge-accent"
                  : "text-neutral-600"
        }`}
      >
        {state === "done"
          ? "COMPLETE"
          : state === "running"
            ? "RUNNING"
            : state === "failed"
              ? "FAILED"
              : state === "ready"
                ? "READY"
                : "LOCKED"}
      </span>
    </div>
  );
}
