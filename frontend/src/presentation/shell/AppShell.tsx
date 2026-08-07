/**
 * AppShell component.
 *
 * Purpose:       Top-level layout shown for Phase 1 — proves the frontend build,
 *                Tailwind, and the API round trip all work together.
 * Responsibility: Compose presentation components; no business logic.
 * Why it exists: From Phase 2 onward this becomes the persistent chrome
 *                (navigation, repository picker) wrapping a router outlet —
 *                established now so later phases have a mount point.
 * Depends on:    presentation/shell/StatusBadge.tsx.
 * Depended on by: App.tsx.
 */

import { StatusBadge } from "@/presentation/shell/StatusBadge";

export function AppShell() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 text-neutral-100">
      <h1 className="text-4xl font-semibold tracking-tight">Forge</h1>
      <p className="text-neutral-400">Turn Code Into Knowledge.</p>
      <StatusBadge />
    </div>
  );
}
