/**
 * RagPanel component.
 *
 * Purpose:       The AI code-intelligence workspace — repository indexing controls,
 *                natural-language questions, grounded answers, and verifiable
 *                file/symbol/line citations with bounded graph context.
 * Responsibility: Composition and presentation of RAG interactions.
 * Depends on:    application/rag/useRepositoryRag.ts, domain/rag/types.ts,
 *                presentation/shared/SummaryStat.tsx.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import { useState } from "react";

import { useRepositoryRag } from "@/application/rag/useRepositoryRag";
import type { SourceReference } from "@/domain/rag/types";
import { SummaryStat } from "@/presentation/shared/SummaryStat";

const SECTION_CLASS = "rounded-lg border border-neutral-800 bg-neutral-900/40 p-4";
const HEADING_CLASS = "mb-3 text-sm font-medium uppercase tracking-wide text-neutral-400";

const EXAMPLE_QUESTIONS = [
  "What is the main architecture and responsibility of this codebase?",
  "How are dependencies analyzed and resolved?",
  "Where and how is error handling implemented?",
] as const;

interface RagPanelProps {
  projectId: string | null;
  repositoryId: string | null;
  /** True once parsing has succeeded so source files and symbols are available. */
  enabled: boolean;
  onNavigateToFile?: (path: string) => void;
  onNavigateToSymbol?: (symbolName: string) => void;
}

export function RagPanel({
  projectId,
  repositoryId,
  enabled,
  onNavigateToFile,
  onNavigateToSymbol,
}: RagPanelProps) {
  const rag = useRepositoryRag(projectId, repositoryId, enabled);
  const [activeChip, setActiveChip] = useState<string | null>(null);

  if (!enabled) return null;

  const status = rag.status.data;
  const isIndexed = rag.isIndexed;
  const latestResult = rag.indexing.data;
  const currentAnswer = rag.ask.data;

  const handleChipClick = (q: string) => {
    setActiveChip(q);
    rag.setQuestion(q);
    void rag.handleAsk(q);
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!rag.canAsk) return;
    void rag.handleAsk();
  };

  return (
    <div className="space-y-4">
      <section className={SECTION_CLASS}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className={HEADING_CLASS}>13 · Code intelligence (Ask Forge)</h2>
          {status && (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                status.indexed
                  ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                  : "bg-amber-950 text-amber-300 border border-amber-800"
              }`}
            >
              {status.indexed ? `Indexed (${status.chunkCount} chunks)` : "Not indexed"}
            </span>
          )}
        </div>

        <p className="mb-4 text-xs text-neutral-400">
          Ask grounded questions about this repository. Semantic retrieval is bounded, strictly
          isolated to this project, and enriched with Neo4j graph context — powered by Qwen 2.5 Coder
          and Nomic Embed.
        </p>

        {/* Index Status & Actions */}
        <div className="mb-4 rounded-md border border-neutral-800/80 bg-neutral-950/60 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-neutral-400">Model:</span>
                <code className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-200">
                  {status?.embeddingModel ?? "nomic-embed-text"}
                </code>
                <span className="text-neutral-600">·</span>
                <span className="text-neutral-400">LLM:</span>
                <code className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-200">
                  qwen2.5-coder:3b
                </code>
                {status?.lastIndexedAt && (
                  <>
                    <span className="text-neutral-600">·</span>
                    <span className="text-neutral-500">
                      Indexed {new Date(status.lastIndexedAt).toLocaleTimeString()}
                    </span>
                  </>
                )}
              </div>
            </div>

            <button
              type="button"
              onClick={() => void rag.handleIndex()}
              disabled={rag.isBusy}
              className={
                "rounded-md px-3 py-1.5 text-xs font-medium text-white transition " +
                (isIndexed
                  ? "bg-neutral-800 hover:bg-neutral-700 text-neutral-200"
                  : "bg-emerald-600 hover:bg-emerald-500") +
                " disabled:cursor-not-allowed disabled:opacity-50"
              }
            >
              {rag.indexing.isPending
                ? "Indexing chunks..."
                : isIndexed
                  ? "Re-index repository"
                  : "Index repository"}
            </button>
          </div>

          {rag.indexing.error && (
            <p role="alert" className="mt-2 text-xs text-red-400">
              Indexing failed: {rag.indexing.error}
            </p>
          )}

          {latestResult && (
            <div className="mt-3 grid grid-cols-2 gap-2 border-t border-neutral-800/60 pt-3 sm:grid-cols-4">
              <SummaryStat label="Chunks" value={latestResult.chunkCount} />
              <SummaryStat label="Embedded" value={latestResult.embeddedCount} />
              <SummaryStat label="Reused vectors" value={latestResult.reusedCount} />
              <SummaryStat label="Files indexed" value={latestResult.filesIndexed} />
            </div>
          )}
        </div>

        {/* Suggestion Chips */}
        <div className="mb-3">
          <p className="mb-1.5 text-xs text-neutral-500">Suggested questions:</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => handleChipClick(example)}
                disabled={rag.isBusy || !isIndexed}
                className={
                  "rounded-full border px-2.5 py-1 text-xs text-left transition " +
                  (activeChip === example
                    ? "border-emerald-700 bg-emerald-950 text-emerald-200"
                    : "border-neutral-800 bg-neutral-900/60 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200") +
                  " disabled:cursor-not-allowed disabled:opacity-40"
                }
              >
                {example}
              </button>
            ))}
          </div>
        </div>

        {/* Question Form */}
        <form onSubmit={handleFormSubmit} className="space-y-2">
          <div className="relative">
            <input
              type="text"
              value={rag.question}
              onChange={(e) => {
                rag.setQuestion(e.target.value);
                setActiveChip(null);
              }}
              placeholder={
                isIndexed
                  ? "Ask about functions, classes, dependencies, or workflows…"
                  : "Index the repository first to enable code intelligence questions"
              }
              disabled={!isIndexed || rag.isBusy}
              className={
                "w-full rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm " +
                "text-neutral-100 placeholder-neutral-500 focus:border-emerald-600 focus:outline-none " +
                "disabled:cursor-not-allowed disabled:bg-neutral-900/50 disabled:text-neutral-600"
              }
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-neutral-500">
              {isIndexed
                ? "Press Enter to query"
                : "Repository must be indexed before querying"}
            </span>

            <button
              type="submit"
              disabled={!rag.canAsk}
              className={
                "rounded-md bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition " +
                "hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-neutral-800 disabled:text-neutral-500"
              }
            >
              {rag.ask.isPending ? "Searching & reasoning…" : "Ask Forge"}
            </button>
          </div>
        </form>

        {rag.ask.error && (
          <div
            role="alert"
            className="mt-3 rounded-md border border-red-900/50 bg-red-950/40 p-3 text-xs text-red-300"
          >
            <p className="font-medium">Query failed</p>
            <p className="mt-0.5 text-red-400">{rag.ask.error}</p>
          </div>
        )}

        {/* Answer Section */}
        {currentAnswer && (
          <div className="mt-4 space-y-3 border-t border-neutral-800/80 pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-neutral-300">
                Answer
              </h3>
              <div className="flex items-center gap-1.5 text-[11px] text-neutral-500">
                <span>{currentAnswer.llmModel}</span>
                <span>via</span>
                <span className="font-mono">{currentAnswer.llmProvider}</span>
              </div>
            </div>

            {!currentAnswer.hasSufficientEvidence ? (
              <div className="rounded-md border border-amber-900/60 bg-amber-950/30 p-3.5 text-xs text-amber-200">
                <div className="flex items-start gap-2">
                  <span className="text-base leading-none">⚠️</span>
                  <div>
                    <p className="font-semibold text-amber-300">Insufficient evidence</p>
                    <p className="mt-1 leading-relaxed text-amber-200/90">{currentAnswer.answer}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-neutral-800 bg-neutral-950/80 p-4">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-200">
                  {currentAnswer.answer}
                </p>
              </div>
            )}

            {/* Citations & Sources */}
            {currentAnswer.sources.length > 0 && (
              <div className="space-y-2 pt-2">
                <h4 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                  Citations &amp; Retrieved Code ({currentAnswer.sources.length})
                </h4>

                <div className="grid grid-cols-1 gap-2">
                  {currentAnswer.sources.map((source, idx) => (
                    <SourceCitationCard
                      key={`${source.path}:${source.startLine}-${source.endLine}:${idx}`}
                      source={source}
                      isSelected={
                        rag.selectedSource?.path === source.path &&
                        rag.selectedSource?.startLine === source.startLine
                      }
                      onSelect={() =>
                        rag.selectSource(
                          rag.selectedSource?.path === source.path &&
                            rag.selectedSource?.startLine === source.startLine
                            ? null
                            : source,
                        )
                      }
                      onNavigateFile={onNavigateToFile}
                      onNavigateSymbol={onNavigateToSymbol}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Bounded Graph Context */}
            {currentAnswer.graphContext.length > 0 && (
              <div className="space-y-2 pt-2">
                <h4 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                  Graph Context ({currentAnswer.graphContext.length} related symbols)
                </h4>

                <div className="flex flex-wrap gap-1.5">
                  {currentAnswer.graphContext.map((item, idx) => (
                    <span
                      key={`${item.qualifiedName}:${idx}`}
                      className="inline-flex items-center gap-1 rounded border border-neutral-800 bg-neutral-900/60 px-2 py-1 text-xs text-neutral-300"
                    >
                      <span className="font-mono text-emerald-400 text-[11px]">
                        {item.relationship}
                      </span>
                      <span className="text-neutral-500 text-[10px]">({item.direction})</span>
                      <span className="font-medium text-neutral-200">{item.qualifiedName}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

interface SourceCitationCardProps {
  source: SourceReference;
  isSelected: boolean;
  onSelect: () => void;
  onNavigateFile?: (path: string) => void;
  onNavigateSymbol?: (symbolName: string) => void;
}

function SourceCitationCard({
  source,
  isSelected,
  onSelect,
  onNavigateFile,
  onNavigateSymbol,
}: SourceCitationCardProps) {
  const matchPercent = Math.round(source.score * 100);

  return (
    <div
      onClick={onSelect}
      className={
        "cursor-pointer rounded border p-2.5 transition text-xs " +
        (isSelected
          ? "border-emerald-700 bg-neutral-900/90 ring-1 ring-emerald-700"
          : "border-neutral-800/80 bg-neutral-950/50 hover:border-neutral-700 hover:bg-neutral-900/40")
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
              source.via === "graph"
                ? "bg-purple-950 text-purple-300 border border-purple-800"
                : "bg-emerald-950 text-emerald-300 border border-emerald-800"
            }`}
          >
            {source.via}
          </span>
          <span className="font-mono text-neutral-200 font-medium">{source.path}</span>
          <span className="font-mono text-neutral-500">
            L{source.startLine}–L{source.endLine}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded bg-neutral-800/80 px-1.5 py-0.5 text-[11px] font-medium text-neutral-300">
            {matchPercent}% match
          </span>
        </div>
      </div>

      {source.symbolQualifiedName && (
        <div className="mt-1.5 flex items-center gap-2 text-neutral-400">
          <span className="text-neutral-500">Symbol:</span>
          <span className="font-mono text-neutral-300">{source.symbolQualifiedName}</span>
          {source.symbolKind && (
            <span className="rounded-full bg-neutral-800 px-1.5 py-0.2 text-[10px] text-neutral-400">
              {source.symbolKind}
            </span>
          )}
        </div>
      )}

      {isSelected && source.snippet && (
        <div className="mt-2.5 rounded bg-neutral-950 p-2.5 border border-neutral-800/80">
          <div className="mb-1 flex items-center justify-between text-[10px] text-neutral-400">
            <span>Retrieved code excerpt:</span>
            <span>Lines {source.startLine}–{source.endLine}</span>
          </div>
          <pre className="max-h-48 overflow-auto font-mono text-[11px] leading-relaxed text-neutral-200">
            <code>{source.snippet}</code>
          </pre>
        </div>
      )}

      {isSelected && (
        <div className="mt-2.5 flex items-center gap-2 border-t border-neutral-800/80 pt-2 text-[11px]">
          {onNavigateFile && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onNavigateFile(source.path);
              }}
              className="rounded bg-neutral-800 px-2 py-0.5 text-neutral-300 hover:bg-neutral-700"
            >
              Filter in Explorer
            </button>
          )}
          {onNavigateSymbol && source.symbolQualifiedName && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (source.symbolQualifiedName) onNavigateSymbol(source.symbolQualifiedName);
              }}
              className="rounded bg-neutral-800 px-2 py-0.5 text-neutral-300 hover:bg-neutral-700"
            >
              Inspect Symbol
            </button>
          )}
          <span className="text-neutral-500 ml-auto">
            Lines {source.startLine} to {source.endLine}
          </span>
        </div>
      )}
    </div>
  );
}

