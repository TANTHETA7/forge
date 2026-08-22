/**
 * SymbolDetails component.
 *
 * Purpose:       Show one selected symbol's full detail, including its parameters.
 * Responsibility: Presentation only.
 * Why it exists: The list rows stay compact (kind, name, line range); everything else
 *                the API returns — qualified name, columns, parent, parameters — is
 *                shown here, fetched only when a symbol is actually selected.
 * Depends on:    domain/explorer/types.ts, presentation/shared/AsyncSection.tsx,
 *                application/shared/useAsyncData.ts (for `AsyncDataState`).
 * Depended on by: presentation/explorer/ExplorerPanel.tsx.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type { CodeSymbol } from "@/domain/explorer/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";

const DT = "text-xs uppercase tracking-wide text-neutral-500";

function position(symbol: CodeSymbol): string {
  const start = symbol.startColumn === null ? "" : `:${symbol.startColumn}`;
  const end = symbol.endColumn === null ? "" : `:${symbol.endColumn}`;
  return `L${symbol.startLine}${start} – L${symbol.endLine}${end}`;
}

export function SymbolDetails({ state }: { state: AsyncDataState<CodeSymbol> }) {
  // `data === null` with nothing loading means no symbol is selected yet.
  if (!state.isLoading && !state.error && state.data === null) {
    return <p className="py-3 text-sm text-neutral-500">Select a symbol to see its details.</p>;
  }

  return (
    <AsyncSection
      state={state}
      loadingMessage="Loading symbol…"
      emptyMessage="No details returned for this symbol."
      isEmpty={() => false}
    >
      {(symbol) => (
        <div className="space-y-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
              {symbol.kind}
            </span>
            <h4 className="font-medium text-neutral-100">{symbol.name}</h4>
          </div>

          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <dt className={DT}>Qualified name</dt>
              <dd className="break-all font-mono text-xs text-neutral-200">
                {symbol.qualifiedName}
              </dd>
            </div>
            <div>
              <dt className={DT}>Position</dt>
              <dd className="font-mono text-xs text-neutral-200">{position(symbol)}</dd>
            </div>
            <div>
              <dt className={DT}>Parent symbol</dt>
              <dd className="break-all font-mono text-xs text-neutral-400">
                {symbol.parentSymbolId ?? "none (top level)"}
              </dd>
            </div>
            <div>
              <dt className={DT}>Symbol id</dt>
              <dd className="break-all font-mono text-xs text-neutral-400">{symbol.id}</dd>
            </div>
          </dl>

          <div>
            <dt className={DT}>Parameters</dt>
            {symbol.parameters.length === 0 ? (
              <p className="mt-1 text-sm text-neutral-500">No parameters.</p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {symbol.parameters
                  .slice()
                  .sort((a, b) => a.position - b.position)
                  .map((parameter) => (
                    <li
                      key={`${parameter.position}-${parameter.name}`}
                      className="font-mono text-xs text-neutral-300"
                    >
                      <span className="text-neutral-500">{parameter.position}.</span>{" "}
                      {parameter.name}
                      {parameter.annotation && (
                        <span className="text-emerald-300">: {parameter.annotation}</span>
                      )}
                      {parameter.defaultValue !== null && (
                        <span className="text-neutral-500"> = {parameter.defaultValue}</span>
                      )}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </AsyncSection>
  );
}
