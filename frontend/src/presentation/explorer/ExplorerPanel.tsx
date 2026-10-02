/**
 * ExplorerPanel component.
 *
 * Purpose:       Read-only exploration of a parsed repository — files, symbols, the
 *                selected symbol's details, and parse errors — as one coherent panel.
 * Responsibility: Composition and rendering only. All requests, filtering, paging, and
 *                 selection state come from `useRepositoryExplorer`.
 * Why it exists: Gives the data the pipeline produced somewhere to be seen, without a
 *                router: it appears below the pipeline once parsing has succeeded.
 * Depends on:    application/explorer/useRepositoryExplorer.ts,
 *                presentation/explorer/{FileList,SymbolList,SymbolDetails,ParseErrorList}.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import { useEffect } from "react";

import { useRepositoryExplorer } from "@/application/explorer/useRepositoryExplorer";
import { FileList } from "@/presentation/explorer/FileList";
import { ParseErrorList } from "@/presentation/explorer/ParseErrorList";
import { SymbolDetails } from "@/presentation/explorer/SymbolDetails";
import { SymbolList } from "@/presentation/explorer/SymbolList";

const SECTION_CLASS = "rounded-lg border border-neutral-800 bg-neutral-900/40 p-4";
const HEADING_CLASS = "mb-3 text-sm font-medium uppercase tracking-wide text-neutral-400";

interface ExplorerPanelProps {
  projectId: string | null;
  repositoryId: string | null;
  /** False until the repository has been parsed — there is nothing to read before then. */
  enabled: boolean;
  selectedFilePath?: string | null;
  selectedSymbolName?: string | null;
  onClearNavigation?: () => void;
}

export function ExplorerPanel({
  projectId,
  repositoryId,
  enabled,
  selectedFilePath,
  selectedSymbolName,
  onClearNavigation,
}: ExplorerPanelProps) {
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
  } = useRepositoryExplorer(projectId, repositoryId, enabled);

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

  if (!enabled) return null;

  const selectedFile = files.data?.find((file) => file.id === fileFilter) ?? null;

  return (
    <div id="explorer-panel" className="space-y-4">
      <section className={SECTION_CLASS}>
        <h2 className={HEADING_CLASS}>5 · Files</h2>
        <FileList state={files} selectedFileId={fileFilter} onSelectFile={setFileFilter} />
      </section>

      <section className={SECTION_CLASS}>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className={`${HEADING_CLASS} mb-0`}>6 · Symbols</h2>
          {selectedFile && (
            <button
              type="button"
              onClick={() => {
                setFileFilter(null);
                onClearNavigation?.();
              }}
              className="rounded-md bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300 hover:bg-neutral-700"
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
          onSelectSymbol={selectSymbol}
          isFileFiltered={fileFilter !== null}
          page={page}
          hasNextPage={hasNextPage}
          onNextPage={nextPage}
          onPreviousPage={previousPage}
        />
      </section>

      <section className={SECTION_CLASS}>
        <h2 className={HEADING_CLASS}>7 · Selected symbol</h2>
        <SymbolDetails state={selectedSymbol} />
      </section>

      <section className={SECTION_CLASS}>
        <h2 className={HEADING_CLASS}>8 · Parse errors</h2>
        <ParseErrorList state={parseErrors} />
      </section>
    </div>
  );
}
