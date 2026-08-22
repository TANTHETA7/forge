/**
 * SummaryStat component.
 *
 * Purpose:       Render one labelled number from a pipeline summary or repository
 *                metadata block.
 * Responsibility: Presentation only — takes a label and value, renders markup.
 * Why it exists: Every stage summary is a row of labelled counts (files, symbols,
 *                edges, nodes, ...). One tile component keeps them visually
 *                identical and keeps the stage components free of repeated markup.
 * Depends on:    nothing.
 * Depended on by: presentation/pipeline/StageCard.tsx,
 *                 presentation/repository/RepositoryCard.tsx.
 */

export type StatTone = "default" | "warn" | "bad";

const TONE_CLASSES: Record<StatTone, string> = {
  default: "text-neutral-100",
  warn: "text-amber-300",
  bad: "text-red-300",
};

interface SummaryStatProps {
  label: string;
  value: string | number;
  /** `warn`/`bad` highlight counts that deserve attention, e.g. unresolved edges. */
  tone?: StatTone;
}

export function SummaryStat({ label, value, tone = "default" }: SummaryStatProps) {
  return (
    <div className="rounded-md bg-neutral-900 px-3 py-2">
      <div className={`text-lg font-semibold tabular-nums ${TONE_CLASSES[tone]}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
    </div>
  );
}
