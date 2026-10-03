import { useEffect, useMemo, useState } from "react";
import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import { useRepositoryExplorer } from "@/application/explorer/useRepositoryExplorer";
import { FileList } from "@/presentation/explorer/FileList";
import { SymbolList } from "@/presentation/explorer/SymbolList";
import { SymbolDetails } from "@/presentation/explorer/SymbolDetails";
import { ParseErrorList } from "@/presentation/explorer/ParseErrorList";
import type { GraphNode } from "@/domain/graph/types";

interface ExplorerWorkspaceProps {
  projectId: string | null;
  repositoryId: string | null;
  enabled: boolean;
  graphNodes?: GraphNode[];
}

export function ExplorerWorkspace({
  projectId,
  repositoryId,
  enabled,
  graphNodes = [],
}: ExplorerWorkspaceProps) {
  const {
    selectedFilePath,
    selectedSymbolName,
    setSelectedFilePath,
    setSelectedSymbolName,
    navigateToGraph,
    navigateToImpact,
    navigateToIntelligence,
  } = useWorkspace();

  const explorer = useRepositoryExplorer(projectId, repositoryId, enabled);
  const {
    files,
    symbols,
    parseErrors,
    selectedSymbol,
    selectedSymbolId,
    selectSymbol,
    kindFilter,
    setKindFilter,
    fileFilter,
    setFileFilter,
    page,
    hasNextPage,
    nextPage,
    previousPage,
  } = explorer;

  const [fileSearch, setFileSearch] = useState("");

  // Sync navigation requests into explorer state
  useEffect(() => {
    if (selectedFilePath && files.data) {
      const match = files.data.find((f) => f.path === selectedFilePath);
      if (match) {
        setFileFilter(match.id);
      }
    }
  }, [selectedFilePath, files.data, setFileFilter]);

  useEffect(() => {
    if (selectedSymbolName && symbols.data) {
      const match = symbols.data.find(
        (s) => s.name === selectedSymbolName || s.qualifiedName === selectedSymbolName,
      );
      if (match) {
        selectSymbol(match.id);
      }
    }
  }, [selectedSymbolName, symbols.data, selectSymbol]);

  const selectedFile = files.data?.find((f) => f.id === fileFilter) ?? null;
  const currentSymbol = selectedSymbol.data;

  // Filter files by search term
  const filteredFilesState = useMemo(() => {
    if (!files.data || !fileSearch.trim()) return files;
    const q = fileSearch.toLowerCase().trim();
    return {
      ...files,
      data: files.data.filter((f) => f.path.toLowerCase().includes(q)),
    };
  }, [files, fileSearch]);

  // Find corresponding graph node for the selected symbol if graph is projected
  const matchingGraphNode = useMemo(() => {
    if (!currentSymbol || !graphNodes.length) return null;
    return (
      graphNodes.find(
        (n) =>
          n.kind === "symbol" &&
          (n.name === currentSymbol.name || n.qualifiedName === currentSymbol.qualifiedName),
      ) ?? null
    );
  }, [currentSymbol, graphNodes]);

  if (!enabled) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-forge-text-muted">
        <div>
          <p className="text-sm font-medium text-forge-text-secondary">
            Explorer is locked
          </p>
          <p className="mt-1 text-xs">
            Run the repository parse stage first to extract source files and symbols.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div id="explorer-panel" className="flex h-[calc(100vh-85px)] overflow-hidden">
      {/* Column 1: Files Sidebar (300px) */}
      <div className="w-80 flex-shrink-0 border-r border-forge-border bg-forge-sidebar/60 flex flex-col justify-between overflow-hidden">
        <div className="p-3 border-b border-forge-border bg-forge-sidebar/90">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-forge-text-muted">
              Source Files ({files.data?.length ?? 0})
            </span>
            {selectedFile && (
              <button
                type="button"
                onClick={() => {
                  setFileFilter(null);
                  setSelectedFilePath(null);
                }}
                className="rounded bg-forge-elevated px-1.5 py-0.5 text-[10px] text-forge-text-muted hover:text-forge-text-primary"
              >
                Clear filter ✕
              </button>
            )}
          </div>
          <input
            type="text"
            value={fileSearch}
            onChange={(e) => setFileSearch(e.target.value)}
            placeholder="Filter files by path…"
            className="w-full rounded-md border border-forge-border bg-forge-panel px-2.5 py-1 text-xs text-forge-text-primary placeholder-forge-text-muted focus:border-forge-accent focus:outline-none"
          />
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          <FileList
            state={filteredFilesState}
            selectedFileId={fileFilter}
            onSelectFile={(id) => {
              setFileFilter(id);
              if (!id) setSelectedFilePath(null);
            }}
          />
        </div>

        {/* Syntax Errors Drawer at bottom of file column */}
        {parseErrors.data && parseErrors.data.length > 0 && (
          <div className="border-t border-forge-border bg-red-950/20 p-3 max-h-48 overflow-y-auto">
            <div className="text-[11px] font-semibold text-red-400 mb-1">
              Parse Errors ({parseErrors.data.length})
            </div>
            <ParseErrorList state={parseErrors} />
          </div>
        )}
      </div>

      {/* Column 2: Center Symbols & Code Overview (flex-1) */}
      <div className="flex-1 flex flex-col bg-forge-bg overflow-hidden">
        {/* Header Breadcrumb */}
        <div className="flex items-center justify-between border-b border-forge-border bg-forge-sidebar/40 px-4 py-2.5 text-xs">
          <div className="flex items-center gap-2 font-mono">
            <span className="text-forge-text-muted">File:</span>
            {selectedFile ? (
              <span className="text-forge-text-primary font-medium">
                {selectedFile.path}
              </span>
            ) : (
              <span className="text-forge-text-muted">All repository files</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {selectedFile && (
              <span className="rounded bg-forge-elevated border border-forge-border px-2 py-0.5 font-mono text-[10px] text-forge-text-secondary">
                {selectedFile.language} · {selectedFile.symbolCount} symbols
              </span>
            )}
          </div>
        </div>

        {/* Symbols list and code view */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="rounded-xl border border-forge-border bg-forge-card p-4">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
                Repository Symbols
              </h2>
              {selectedFile && (
                <button
                  type="button"
                  onClick={() => {
                    setFileFilter(null);
                    setSelectedFilePath(null);
                  }}
                  className="rounded-md bg-forge-elevated border border-forge-border px-2 py-0.5 text-xs text-forge-text-secondary hover:text-forge-text-primary"
                >
                  filtered to {selectedFile.path} ✕
                </button>
              )}
            </div>

            <SymbolList
              state={symbols}
              kindFilter={kindFilter}
              onKindChange={setKindFilter}
              selectedSymbolId={selectedSymbolId}
              onSelectSymbol={(id) => {
                selectSymbol(id);
                const sym = symbols.data?.find((s) => s.id === id);
                if (sym) setSelectedSymbolName(sym.name);
              }}
              isFileFiltered={fileFilter !== null}
              page={page}
              hasNextPage={hasNextPage}
              onNextPage={nextPage}
              onPreviousPage={previousPage}
            />
          </div>
        </div>
      </div>

      {/* Column 3: Contextual Symbol Details (340px) */}
      <div className="w-88 flex-shrink-0 border-l border-forge-border bg-forge-sidebar/60 flex flex-col justify-between overflow-y-auto">
        <div className="p-4 space-y-4">
          <div className="flex items-center justify-between border-b border-forge-border pb-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
              Symbol Details
            </span>
            {currentSymbol && (
              <span className="rounded bg-forge-accent/20 text-forge-accent font-mono text-[10px] uppercase px-1.5 py-0.5 font-semibold">
                {currentSymbol.kind}
              </span>
            )}
          </div>

          <SymbolDetails state={selectedSymbol} />

          {/* Cross-linking action buttons when a symbol is selected */}
          {currentSymbol && (
            <div className="pt-3 border-t border-forge-border space-y-2">
              <div className="text-[11px] font-semibold text-forge-text-muted uppercase tracking-wider">
                Cross-Workspace Actions
              </div>

              <div className="grid grid-cols-1 gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (matchingGraphNode) {
                      navigateToGraph(matchingGraphNode);
                    } else {
                      navigateToGraph();
                    }
                  }}
                  className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel px-3 py-2 text-xs text-forge-text-primary hover:bg-forge-elevated transition"
                >
                  <span className="flex items-center gap-2">
                    <svg
                      className="h-3.5 w-3.5 text-forge-accent"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <circle cx="6" cy="6" r="3" />
                      <circle cx="18" cy="6" r="3" />
                      <circle cx="12" cy="18" r="3" />
                      <path d="M8.5 7.5l7 0" />
                    </svg>
                    <span>Focus on Graph</span>
                  </span>
                  <span className="text-[10px] text-forge-text-muted">→</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    if (matchingGraphNode) {
                      navigateToImpact(matchingGraphNode);
                    } else {
                      navigateToImpact();
                    }
                  }}
                  className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel px-3 py-2 text-xs text-forge-text-primary hover:bg-forge-elevated transition"
                >
                  <span className="flex items-center gap-2">
                    <svg
                      className="h-3.5 w-3.5 text-amber-400"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                    </svg>
                    <span>Analyze Change Impact</span>
                  </span>
                  <span className="text-[10px] text-forge-text-muted">→</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    navigateToIntelligence(
                      `Explain the role and implementation of symbol ${currentSymbol.qualifiedName} in this codebase.`,
                    );
                  }}
                  className="flex items-center justify-between rounded-lg border border-forge-accent/40 bg-forge-accent/10 px-3 py-2 text-xs text-forge-accent hover:bg-forge-accent/20 transition font-medium"
                >
                  <span className="flex items-center gap-2">
                    <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                    </svg>
                    <span>Ask Forge about Symbol</span>
                  </span>
                  <span className="text-[10px]">AI</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
