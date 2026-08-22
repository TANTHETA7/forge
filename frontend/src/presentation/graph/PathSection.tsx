/**
 * PathSection component.
 *
 * Purpose:       Find the shortest dependency path from the selected node to a chosen
 *                target, and show the ordered result.
 * Responsibility: Presentation and local control wiring only.
 * Why it exists: `/graph/path` requires both `source_id` and `target_id`, so the UI must
 *                gather a target before it can ask. The traversal is Neo4j's — no
 *                client-side graph walk is implemented here. The run button stays
 *                disabled until both ends exist, so an incomplete request is never sent.
 * Depends on:    domain/graph/types.ts, application/shared/useAsyncAction.ts,
 *                presentation/graph/graphStyles.ts.
 * Depended on by: presentation/graph/NodeIntelligencePanel.tsx.
 */

import type { AsyncActionState } from "@/application/shared/useAsyncAction";
import { graphNodeLabel, type DependencyPath, type GraphNode } from "@/domain/graph/types";
import { NODE_KIND_STYLE, relationshipColor } from "@/presentation/graph/graphStyles";

interface PathSectionProps {
  state: AsyncActionState<DependencyPath>;
  source: GraphNode | null;
  target: GraphNode | null;
  onClearTarget: () => void;
  depth: number;
  onDepthChange: (depth: number) => void;
  maxDepth: number;
  canRun: boolean;
  onRun: () => void;
  onSelectNode: (node: GraphNode) => void;
}

export function PathSection({
  state,
  source,
  target,
  onClearTarget,
  depth,
  onDepthChange,
  maxDepth,
  canRun,
  onRun,
  onSelectNode,
}: PathSectionProps) {
  const path = state.data;

  return (
    <div className="space-y-3">
      <div className="space-y-1 text-sm">
        <p className="text-neutral-400">
          <span className="text-xs uppercase tracking-wide text-neutral-500">Source</span>{" "}
          <span className="font-mono text-xs text-neutral-100">
            {source ? graphNodeLabel(source) : "none"}
          </span>
        </p>
        <p className="text-neutral-400">
          <span className="text-xs uppercase tracking-wide text-neutral-500">Target</span>{" "}
          {target ? (
            <>
              <span className="font-mono text-xs text-neutral-100">{graphNodeLabel(target)}</span>{" "}
              <button
                type="button"
                onClick={onClearTarget}
                className="rounded bg-neutral-800 px-1.5 py-0.5 text-xs text-neutral-300 hover:bg-neutral-700"
              >
                clear
              </button>
            </>
          ) : (
            <span className="text-xs text-neutral-500">
              none — click “Set as path target” on a node
            </span>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label
            className="mb-1 block text-xs uppercase tracking-wide text-neutral-500"
            htmlFor="path-depth"
          >
            Max depth (1–{maxDepth})
          </label>
          <input
            id="path-depth"
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
          disabled={!canRun || state.isPending}
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white disabled:cursor-not-allowed disabled:bg-neutral-800 disabled:text-neutral-500"
        >
          {state.isPending ? "Searching…" : "Find path"}
        </button>
      </div>

      {!canRun && !state.isPending && (
        <p className="text-xs text-neutral-500">
          A source and a target are both required before a path can be requested.
        </p>
      )}

      {state.error && (
        <p role="alert" className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
          {state.error}
        </p>
      )}

      {path && !path.found && (
        <div className="rounded-md bg-neutral-900 px-3 py-2 text-sm text-neutral-400">
          <p>No path found within depth {depth}.</p>
          {/* Verified against the live backend: containment edges are not traversed, so
              two nodes joined only by contains/defines legitimately report no path. */}
          <p className="mt-1 text-xs text-neutral-500">
            Path finding follows dependency edges — imports, calls, inherits. Structural
            containment (contains, defines) is not traversed, so a file and the symbols it
            defines have no path between them.
          </p>
        </div>
      )}

      {path?.found && (
        <div className="space-y-2">
          <p className="text-xs text-neutral-500">
            Path found · length {path.length ?? path.nodes.length - 1} hop
            {(path.length ?? path.nodes.length - 1) === 1 ? "" : "s"} · {path.nodes.length} nodes
          </p>
          <ol className="space-y-1">
            {path.nodes.map((node, index) => (
              <li key={`${node.id}:${index}`} className="flex flex-col gap-1">
                <button
                  type="button"
                  onClick={() => onSelectNode(node)}
                  className="flex flex-wrap items-baseline gap-2 px-1 py-1 text-left text-sm hover:bg-neutral-900"
                >
                  <span className="font-mono text-[10px] text-neutral-500">{index + 1}.</span>
                  <span
                    className={`rounded px-1 py-0.5 text-[10px] uppercase ${
                      NODE_KIND_STYLE[node.kind].badge
                    }`}
                  >
                    {NODE_KIND_STYLE[node.kind].label}
                  </span>
                  <span className="break-all font-mono text-xs text-neutral-200">
                    {graphNodeLabel(node)}
                  </span>
                </button>
                {/* The relationship that leads to the next node in the path. */}
                {path.relationships[index] && (
                  <span
                    className="ml-6 font-mono text-[10px] uppercase"
                    style={{ color: relationshipColor(path.relationships[index].kind) }}
                  >
                    ↓ {path.relationships[index].kind}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
