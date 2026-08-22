/**
 * AppShell component.
 *
 * Purpose:       Persistent chrome — product identity, backend health, and the
 *                current screen's content.
 * Responsibility: Compose presentation components; no business logic.
 * Why it exists: Phase 1 established this as the mount point for later phases; from
 *                Phase 2 it wraps the repository pipeline. There is still only one
 *                screen, so no router is involved — when a second screen arrives,
 *                the `<main>` here is where an outlet goes.
 * Depends on:    presentation/shell/StatusBadge.tsx,
 *                presentation/pipeline/PipelinePanel.tsx.
 * Depended on by: App.tsx.
 */

import { StatusBadge } from "@/presentation/shell/StatusBadge";
import { PipelinePanel } from "@/presentation/pipeline/PipelinePanel";

export function AppShell() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="border-b border-neutral-800">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Forge</h1>
            <p className="text-sm text-neutral-400">Turn Code Into Knowledge.</p>
          </div>
          <StatusBadge />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        <PipelinePanel />
      </main>
    </div>
  );
}
