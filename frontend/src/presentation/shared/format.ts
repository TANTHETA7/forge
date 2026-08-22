/**
 * Presentation formatting helpers.
 *
 * Purpose:       Turn raw domain values (byte counts, ISO timestamps, language
 *                percentage maps) into display strings.
 * Responsibility: Pure formatting — no React, no fetching, no domain rules.
 * Why it exists: Kept out of the components themselves so several components can
 *                format the same way, and so it lives in a `.ts` file rather than
 *                a `.tsx` one (eslint's `react-refresh/only-export-components`
 *                wants component files to export only components).
 * Depended on by: presentation/repository/RepositoryCard.tsx.
 */

const UNITS = ["B", "KB", "MB", "GB"] as const;

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? value : Math.round(value * 10) / 10;
  return `${rounded} ${UNITS[unit]}`;
}

/** Render an ISO-8601 timestamp in the viewer's locale, or "—" if unparseable. */
export function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString();
}

/**
 * Format a `{ Python: 100.0 }` language map as a share-ordered summary,
 * e.g. "Python 100%, TypeScript 12.5%".
 */
export function formatLanguages(stats: Record<string, number>): string {
  const entries = Object.entries(stats).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return "No languages detected";
  return entries.map(([name, share]) => `${name} ${Math.round(share * 10) / 10}%`).join(", ");
}
