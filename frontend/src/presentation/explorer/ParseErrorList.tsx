/**
 * ParseErrorList component.
 *
 * Purpose:       Show the parse failures the backend actually recorded, or state
 *                plainly that there were none.
 * Responsibility: Presentation only.
 * Why it exists: Parse errors are legitimate output, not something to hide. The empty
 *                case is stated explicitly ("no errors") rather than rendering nothing,
 *                so a clean parse is distinguishable from a panel that failed to load.
 * Depends on:    domain/explorer/types.ts, presentation/shared/AsyncSection.tsx,
 *                application/shared/useAsyncData.ts (for `AsyncDataState`).
 * Depended on by: presentation/explorer/ExplorerPanel.tsx.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type { ParseError } from "@/domain/explorer/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";

export function ParseErrorList({ state }: { state: AsyncDataState<ParseError[]> }) {
  return (
    <AsyncSection
      state={state}
      loadingMessage="Loading parse errors…"
      emptyMessage="No parse errors — every discovered file parsed cleanly."
    >
      {(errors) => (
        <ul className="space-y-2">
          {errors.map((error, index) => (
            // The API returns no id for parse errors, so the key is composed.
            <li
              key={`${error.filePath}:${error.stage}:${index}`}
              className="rounded-md bg-red-950/60 px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-xs text-red-200">{error.filePath}</span>
                <span className="rounded-full bg-red-900 px-2 py-0.5 text-xs text-red-200">
                  {error.stage}
                </span>
              </div>
              <p className="mt-1 text-sm text-red-300">{error.message}</p>
            </li>
          ))}
        </ul>
      )}
    </AsyncSection>
  );
}
