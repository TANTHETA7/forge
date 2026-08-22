/**
 * StageCard component.
 *
 * Purpose:       Render one pipeline stage — its name, current state, run button,
 *                error, and (via `children`) its summary once it succeeds.
 * Responsibility: Presentation only. The parent decides whether the stage can run;
 *                 this component reflects that decision.
 * Why it exists: parse / analyze-dependencies / graph-projection differ only in
 *                their label and their summary numbers. One card component keeps
 *                their loading, error, locked, and empty states identical instead of
 *                triplicated.
 * Depends on:    application/pipeline/useRepositoryPipeline.ts (for `StageState`),
 *                domain/pipeline/types.ts.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import type { ReactNode } from "react";

import type { StageState } from "@/application/pipeline/useRepositoryPipeline";

const STATE_BADGE: Record<StageState, { label: string; className: string }> = {
  locked: { label: "locked", className: "bg-neutral-800 text-neutral-500" },
  ready: { label: "ready", className: "bg-neutral-800 text-neutral-300" },
  running: { label: "running", className: "bg-amber-950 text-amber-300" },
  done: { label: "done", className: "bg-emerald-950 text-emerald-300" },
  failed: { label: "failed", className: "bg-red-950 text-red-300" },
};

interface StageCardProps {
  step: number;
  title: string;
  description: string;
  state: StageState;
  error: string | null;
  runLabel: string;
  onRun: () => void;
  children?: ReactNode;
}

export function StageCard({
  step,
  title,
  description,
  state,
  error,
  runLabel,
  onRun,
  children,
}: StageCardProps) {
  const badge = STATE_BADGE[state];
  const isRunnable = state === "ready" || state === "failed";

  return (
    <div
      className={
        "rounded-lg border p-4 transition-opacity " +
        (state === "locked"
          ? "border-neutral-800 bg-neutral-950 opacity-60"
          : "border-neutral-700 bg-neutral-950")
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-medium text-neutral-100">
            <span className="text-neutral-500">{step}.</span> {title}
          </h3>
          <p className="mt-0.5 text-xs text-neutral-500">{description}</p>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs ${badge.className}`}>
          {badge.label}
        </span>
      </div>

      {error && (
        <p role="alert" className="mt-3 rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {children && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">{children}</div>}

      {state === "locked" && (
        <p className="mt-3 text-xs text-neutral-600">Waiting on the previous stage.</p>
      )}

      {isRunnable && (
        <button
          type="button"
          onClick={onRun}
          className={
            "mt-3 rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 " +
            "hover:bg-white"
          }
        >
          {state === "failed" ? `Retry ${runLabel}` : runLabel}
        </button>
      )}

      {state === "running" && (
        <p className="mt-3 text-sm text-amber-300">Running — this may take a few seconds…</p>
      )}
    </div>
  );
}
