/**
 * ImpactSection component.
 *
 * Purpose:       Run multi-hop impact analysis for the selected node and show what the
 *                backend returned.
 * Responsibility: Presentation and local control wiring only. The traversal itself runs
 *                 in Neo4j via `/graph/nodes/{id}/impact`.
 * Why it exists: Impact is an explicit user action with parameters, so it needs controls
 *                and a run button rather than firing on selection. Only the two
 *                directions `DependencyDirection` defines are offered, and depth is
 *                clamped by the hook before any request is sent — the UI cannot
 *                construct a request the backend would reject.
 * Depends on:    domain/graph/types.ts, application/shared/useAsyncAction.ts,
 *                presentation/graph/graphStyles.ts.
 * Depended on by: presentation/graph/NodeIntelligencePanel.tsx.
 */

import type { AsyncActionState } from "@/application/shared/useAsyncAction";
import {
  graphNodeLabel,
  IMPACT_DIRECTIONS,
  type GraphNode,
  type ImpactAnalysis,
  type ImpactDirection,
} from "@/domain/graph/types";
import { NODE_KIND_STYLE, relationshipColor } from "@/presentation/graph/graphStyles";

interface ImpactSectionProps {
  state: AsyncActionState<ImpactAnalysis>;
  direction: ImpactDirection;
  onDirectionChange: (direction: ImpactDirection) => void;
  depth: number;
  onDepthChange: (depth: number) => void;
  maxDepth: number;
  onRun: () => void;
  onSelectNode: (node: GraphNode) => void;
}

export function ImpactSection({
  state,
  direction,
  onDirectionChange,
  depth,
  onDepthChange,
  maxDepth,
  onRun,
  onSelectNode,
}: ImpactSectionProps) {
  const analysis = state.data;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <span className="mb-1 block text-xs uppercase tracking-wide text-neutral-500">
            Direction
          </span>
          <div className="flex gap-1.5" role="group" aria-label="Impact direction">
            {IMPACT_DIRECTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={direction === option}
                disabled={state.isPending}
                onClick={() => onDirectionChange(option)}
                className={
                  "rounded-md px-2.5 py-1 text-xs disabled:opacity-50 " +
                  (direction === option
                    ? "bg-neutral-100 font-medium text-neutral-900"
                    : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700")
                }
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-500"
            htmlFor="impact-depth"
          >
            Depth (1–{maxDepth})
          </label>
          <input
            id="impact-depth"
            type="number"
            min={1}
            max={maxDepth}
            value={depth}
            disabled={state.isPending}
            onChange={(e) => onDepthChange(Number(e.target.value))}
            className="w-20 rounded-md border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-100 disabled:opacity-50"
          />
        </div>

        <button
          type="button"
          onClick={onRun}
          disabled={state.isPending}
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:cursor-not-allowed disabled:bg-neutral-800 disabled:text-neutral-500"
        >
          {state.isPending ? "Analysing…" : "Run impact analysis"}
        </button>
      </div>

      {state.isPending && (
        <p className="text-sm text-amber-300">Traversing the graph — this may take a moment…</p>
      )}

      {state.error && (
        <p role="alert" className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
          {state.error}
        </p>
      )}

      {!state.isPending && !state.error && analysis === null && (
        <p className="text-sm text-neutral-500">
          Choose a direction and depth, then run the analysis.
        </p>
      )}

      {analysis && (
        <div className="space-y-2">
          <p className="text-xs text-neutral-500">
            {analysis.direction} · max depth {analysis.maxDepth} ·{" "}
            {analysis.impactedNodes.length} impacted node
            {analysis.impactedNodes.length === 1 ? "" : "s"}
          </p>

          {analysis.impactedNodes.length === 0 ? (
            <p className="text-sm text-neutral-500">
              Nothing is impacted {analysis.direction} of this node within depth{" "}
              {analysis.maxDepth}.
            </p>
          ) : (
            <ul className="divide-y divide-neutral-800">
              {analysis.impactedNodes.map((impacted, index) => (
                <li key={`${impacted.node.id}:${impacted.relationshipKind}:${index}`}>
                  <button
                    type="button"
                    onClick={() => onSelectNode(impacted.node)}
                    className="flex w-full flex-wrap items-baseline gap-2 px-1 py-1.5 text-left text-sm hover:bg-neutral-900"
                  >
                    {/* Depth is the shortest hop count the backend found. */}
                    <span className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300">
                      depth {impacted.depth}
                    </span>
                    <span
                      className="font-mono text-[10px] uppercase"
                      style={{ color: relationshipColor(impacted.relationshipKind) }}
                    >
                      {impacted.relationshipKind}
                    </span>
                    <span
                      className={`rounded px-1 py-0.5 text-[10px] uppercase ${
                        NODE_KIND_STYLE[impacted.node.kind].badge
                      }`}
                    >
                      {NODE_KIND_STYLE[impacted.node.kind].label}
                    </span>
                    <span className="break-all font-mono text-xs text-neutral-200">
                      {graphNodeLabel(impacted.node)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
