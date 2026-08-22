/**
 * RepositoryCard component.
 *
 * Purpose:       Show an imported repository's identity, status, and scan metadata.
 * Responsibility: Presentation only — renders the `Repository` it is given.
 * Why it exists: Import is synchronous, so metadata is already populated by the time
 *                this renders; the card is the "import succeeded, here is what we
 *                got" half of the slice's result display.
 * Depends on:    domain/repository/types.ts, presentation/shared/{SummaryStat,format}.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import type { Repository, RepositoryStatus } from "@/domain/repository/types";
import { SummaryStat } from "@/presentation/shared/SummaryStat";
import { formatBytes, formatLanguages, formatTimestamp } from "@/presentation/shared/format";

const STATUS_CLASSES: Record<RepositoryStatus, string> = {
  ready: "bg-emerald-950 text-emerald-300",
  pending: "bg-neutral-800 text-neutral-300",
  importing: "bg-amber-950 text-amber-300",
  failed: "bg-red-950 text-red-300",
};

export function RepositoryCard({ repository }: { repository: Repository }) {
  const { metadata } = repository;

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium text-neutral-100">{repository.displayName}</h3>
          <p className="text-xs text-neutral-500">
            {repository.sourceType.toUpperCase()} · imported {formatTimestamp(repository.createdAt)}
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs ${STATUS_CLASSES[repository.status]}`}
        >
          {repository.status}
        </span>
      </div>

      {repository.errorMessage && (
        <p role="alert" className="mt-3 rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
          {repository.errorMessage}
        </p>
      )}

      {metadata ? (
        <>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <SummaryStat label="Files" value={metadata.fileCount} />
            <SummaryStat label="Directories" value={metadata.directoryCount} />
            <SummaryStat label="Size" value={formatBytes(metadata.totalSizeBytes)} />
          </div>
          <dl className="mt-3 space-y-1 text-xs text-neutral-400">
            <div className="flex gap-2">
              <dt className="text-neutral-500">Languages</dt>
              <dd>{formatLanguages(metadata.languageStats)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-neutral-500">Contains</dt>
              <dd>
                {[metadata.hasReadme ? "README" : null, metadata.hasGit ? ".git" : null]
                  .filter(Boolean)
                  .join(", ") || "no README or .git"}
              </dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="mt-3 text-sm text-neutral-500">
          No scan metadata yet — it is populated once the import reaches “ready”.
        </p>
      )}
    </div>
  );
}
