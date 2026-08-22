/**
 * FileList component.
 *
 * Purpose:       List a parsed repository's files with the counts the API already
 *                returns, and let one be selected to scope the symbol list.
 * Responsibility: Presentation only — it renders the state it is given and reports
 *                 selection upward.
 * Why it exists: `/files` returns per-file counts directly, so the file list needs no
 *                nested symbol or import requests to be useful.
 * Depends on:    domain/explorer/types.ts, presentation/shared/AsyncSection.tsx,
 *                application/shared/useAsyncData.ts (for `AsyncDataState`).
 * Depended on by: presentation/explorer/ExplorerPanel.tsx.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type { ParsedFile } from "@/domain/explorer/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";

interface FileListProps {
  state: AsyncDataState<ParsedFile[]>;
  selectedFileId: string | null;
  onSelectFile: (fileId: string | null) => void;
}

export function FileList({ state, selectedFileId, onSelectFile }: FileListProps) {
  return (
    <AsyncSection
      state={state}
      loadingMessage="Loading files…"
      emptyMessage="No parsed files. Run the parse stage first."
    >
      {(files) => (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-neutral-500">
                <th className="py-1.5 pr-3 font-normal">Path</th>
                <th className="py-1.5 pr-3 font-normal">Language</th>
                <th className="py-1.5 pr-3 text-right font-normal">Symbols</th>
                <th className="py-1.5 pr-3 text-right font-normal">Imports</th>
                <th className="py-1.5 font-normal">Syntax</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const isSelected = file.id === selectedFileId;
                return (
                  <tr
                    key={file.id}
                    onClick={() => onSelectFile(isSelected ? null : file.id)}
                    aria-selected={isSelected}
                    className={
                      "cursor-pointer border-t border-neutral-800 " +
                      (isSelected ? "bg-neutral-800" : "hover:bg-neutral-900")
                    }
                  >
                    <td className="py-1.5 pr-3 font-mono text-xs text-neutral-200">{file.path}</td>
                    <td className="py-1.5 pr-3 text-neutral-400">{file.language}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums text-neutral-300">
                      {file.symbolCount}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums text-neutral-300">
                      {file.importCount}
                    </td>
                    <td className="py-1.5">
                      {file.hasSyntaxErrors ? (
                        <span className="rounded-full bg-red-950 px-2 py-0.5 text-xs text-red-300">
                          errors
                        </span>
                      ) : (
                        <span className="text-xs text-neutral-600">clean</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-neutral-600">
            {files.length} file{files.length === 1 ? "" : "s"}
            {selectedFileId ? " · click the selected row again to clear the filter" : " · click a row to filter symbols"}
          </p>
        </div>
      )}
    </AsyncSection>
  );
}
