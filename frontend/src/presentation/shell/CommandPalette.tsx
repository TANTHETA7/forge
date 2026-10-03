import { useEffect, useMemo, useState, useRef } from "react";
import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import type { ParsedFile, CodeSymbol } from "@/domain/explorer/types";

interface CommandPaletteProps {
  files: ParsedFile[];
  symbols: CodeSymbol[];
  canRunPipeline?: boolean;
  onRunRemaining?: () => void;
  onTriggerIndex?: () => void;
}

interface CommandItem {
  id: string;
  category: "Navigation" | "Action" | "File" | "Symbol";
  title: string;
  subtitle?: string;
  badge?: string;
  action: () => void;
}

export function CommandPalette({
  files,
  symbols,
  canRunPipeline,
  onRunRemaining,
  onTriggerIndex,
}: CommandPaletteProps) {
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    navigateToOverview,
    navigateToExplorer,
    navigateToGraph,
    navigateToImpact,
    navigateToIntelligence,
  } = useWorkspace();

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global keyboard listener for Command+K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      } else if (e.key === "Escape" && commandPaletteOpen) {
        e.preventDefault();
        setCommandPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  // Focus input and reset search when opened
  useEffect(() => {
    if (commandPaletteOpen) {
      const timer = setTimeout(() => {
        setQuery("");
        setSelectedIndex(0);
        inputRef.current?.focus();
      }, 10);
      return () => clearTimeout(timer);
    }
  }, [commandPaletteOpen]);

  // Build commands
  const allCommands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = [
      {
        id: "nav-overview",
        category: "Navigation",
        title: "Overview",
        subtitle: "Repository metrics, pipeline status, and graph insights",
        badge: "1",
        action: () => {
          navigateToOverview();
          setCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-explorer",
        category: "Navigation",
        title: "Explorer",
        subtitle: "Navigate codebase files, symbol AST, and code definitions",
        badge: "2",
        action: () => {
          navigateToExplorer();
          setCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-graph",
        category: "Navigation",
        title: "Repository Graph",
        subtitle: "Interactive Neo4j dependency network and focus modes",
        badge: "3",
        action: () => {
          navigateToGraph();
          setCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-impact",
        category: "Navigation",
        title: "Impact Analysis",
        subtitle: "Trace multi-hop blast radius of code changes",
        badge: "4",
        action: () => {
          navigateToImpact();
          setCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-intelligence",
        category: "Navigation",
        title: "Forge Intelligence",
        subtitle: "Grounded Qwen 2.5 Coder code queries with real citations",
        badge: "5",
        action: () => {
          navigateToIntelligence();
          setCommandPaletteOpen(false);
        },
      },
    ];

    if (canRunPipeline && onRunRemaining) {
      items.push({
        id: "act-run-pipeline",
        category: "Action",
        title: "Run Remaining Pipeline Stages",
        subtitle: "Execute pending parse, analyze, or graph projection",
        badge: "Action",
        action: () => {
          onRunRemaining();
          setCommandPaletteOpen(false);
        },
      });
    }

    if (onTriggerIndex) {
      items.push({
        id: "act-index-ai",
        category: "Action",
        title: "Index Repository Vectors",
        subtitle: "Generate nomic-embed-text chunks for code RAG",
        badge: "AI",
        action: () => {
          onTriggerIndex();
          setCommandPaletteOpen(false);
        },
      });
    }

    // Add Files (limit to top 40 for responsiveness)
    files.slice(0, 40).forEach((file) => {
      items.push({
        id: `file-${file.id}`,
        category: "File",
        title: file.path,
        subtitle: `${file.language} · ${file.symbolCount} symbols · ${file.importCount} imports`,
        badge: file.language.slice(0, 2).toUpperCase(),
        action: () => {
          navigateToExplorer(file.path, null);
          setCommandPaletteOpen(false);
        },
      });
    });

    // Add Symbols (limit to top 50)
    symbols.slice(0, 50).forEach((sym) => {
      items.push({
        id: `sym-${sym.id}`,
        category: "Symbol",
        title: sym.name,
        subtitle: `${sym.qualifiedName} (Lines ${sym.startLine}–${sym.endLine})`,
        badge: sym.kind.slice(0, 3).toUpperCase(),
        action: () => {
          navigateToExplorer(null, sym.name);
          setCommandPaletteOpen(false);
        },
      });
    });

    return items;
  }, [
    files,
    symbols,
    canRunPipeline,
    onRunRemaining,
    onTriggerIndex,
    navigateToOverview,
    navigateToExplorer,
    navigateToGraph,
    navigateToImpact,
    navigateToIntelligence,
    setCommandPaletteOpen,
  ]);

  // Filter commands by query
  const filteredCommands = useMemo(() => {
    if (!query.trim()) return allCommands;
    const q = query.toLowerCase().trim();
    return allCommands.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
        item.category.toLowerCase().includes(q),
    );
  }, [allCommands, query]);

  // Handle arrow keys and Enter
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev <= 0 ? filteredCommands.length - 1 : prev - 1,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
      }
    }
  };

  if (!commandPaletteOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/80 backdrop-blur-sm"
      onClick={() => setCommandPaletteOpen(false)}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-xl border border-forge-border bg-forge-card shadow-2xl transition-all"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="relative flex items-center border-b border-forge-border px-4 py-3 bg-forge-elevated">
          <svg
            className="mr-3 h-4 w-4 text-forge-text-muted"
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
          <input
            ref={inputRef}
            data-testid="command-palette-input"
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type a command, file path, symbol, or query..."
            className="w-full bg-transparent text-sm text-forge-text-primary placeholder-forge-text-muted focus:outline-none"
          />
          <kbd className="rounded border border-forge-border bg-forge-sidebar px-2 py-0.5 text-[10px] text-forge-text-muted">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="max-h-96 overflow-y-auto p-2 space-y-1">
          {filteredCommands.length === 0 ? (
            <div className="py-8 text-center text-xs text-forge-text-muted">
              No matching files, symbols, or commands found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            filteredCommands.map((item, index) => {
              const isSelected = index === selectedIndex;
              return (
                <div
                  key={item.id}
                  onClick={() => item.action()}
                  onMouseEnter={() => setSelectedIndex(index)}
                  className={`flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-xs transition ${
                    isSelected
                      ? "bg-forge-accent/15 text-forge-text-primary ring-1 ring-forge-accent/40"
                      : "text-forge-text-secondary hover:bg-forge-elevated"
                  }`}
                >
                  <div className="flex items-center gap-2.5 overflow-hidden">
                    <span
                      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase font-semibold ${
                        item.category === "Navigation"
                          ? "bg-forge-accent/20 text-forge-accent"
                          : item.category === "Action"
                            ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                            : item.category === "File"
                              ? "bg-sky-950 text-sky-300 border border-sky-800"
                              : "bg-purple-950 text-purple-300 border border-purple-800"
                      }`}
                    >
                      {item.badge ?? item.category}
                    </span>
                    <div className="truncate">
                      <div className="font-medium text-forge-text-primary truncate">
                        {item.title}
                      </div>
                      {item.subtitle && (
                        <div className="text-[11px] text-forge-text-muted truncate">
                          {item.subtitle}
                        </div>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] text-forge-text-muted uppercase tracking-wider ml-2">
                    {item.category}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="flex items-center justify-between border-t border-forge-border bg-forge-sidebar px-4 py-2 text-[11px] text-forge-text-muted">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="rounded border border-forge-border bg-forge-card px-1 py-0.5 text-[10px]">
                ↑↓
              </kbd>{" "}
              Navigate
            </span>
            <span>
              <kbd className="rounded border border-forge-border bg-forge-card px-1 py-0.5 text-[10px]">
                ↵
              </kbd>{" "}
              Select
            </span>
          </div>
          <span>Forge Workspace Search</span>
        </div>
      </div>
    </div>
  );
}
