/**
 * NodeIntelligencePanel component.
 *
 * Purpose:       The selected node's workspace — overview, dependencies, dependents,
 *                impact, and path — behind one set of tabs.
 * Responsibility: Composition and tab routing only. Every read and every parameter
 *                 lives in `useRepositoryGraph`; this decides what to show.
 * Why it exists: These five views all concern one node, so they belong in one surface
 *                rather than five screens. Tabs also keep the panel compact on a real
 *                repository, where a dependents list can be long.
 *
 *                Path finding needs two endpoints but there is only one selection, so
 *                the header carries a "Set as path target" action: pin one node as the
 *                target, then select another as the source.
 *
 * Depends on:    application/graph/useRepositoryGraph.ts (types),
 *                presentation/graph/{NodeDetailsPanel,NeighborList,ImpactSection,PathSection}.
 * Depended on by: presentation/graph/GraphPanel.tsx.
 */

import type { NodeTab } from "@/application/graph/useRepositoryGraph";
import type { AsyncActionState } from "@/application/shared/useAsyncAction";
import type { AsyncDataState } from "@/application/shared/useAsyncData";
import {
  graphNodeLabel,
  type DependencyPath,
  type GraphNeighbor,
  type GraphNode,
  type ImpactAnalysis,
  type ImpactDirection,
} from "@/domain/graph/types";
import { ImpactSection } from "@/presentation/graph/ImpactSection";
import { NeighborList } from "@/presentation/graph/NeighborList";
import { NodeDetailsPanel } from "@/presentation/graph/NodeDetailsPanel";
import { PathSection } from "@/presentation/graph/PathSection";

const TABS: readonly { id: NodeTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "dependencies", label: "Dependencies" },
  { id: "dependents", label: "Dependents" },
  { id: "impact", label: "Impact" },
  { id: "path", label: "Path" },
];

interface NodeIntelligencePanelProps {
  selectedNode: GraphNode | null;
  activeTab: NodeTab;
  onTabChange: (tab: NodeTab) => void;
  onSelectNode: (node: GraphNode) => void;

  neighbors: AsyncDataState<GraphNeighbor[]>;
  dependencies: AsyncDataState<GraphNeighbor[]>;
  dependents: AsyncDataState<GraphNeighbor[]>;

  impact: AsyncActionState<ImpactAnalysis>;
  impactDirection: ImpactDirection;
  onImpactDirectionChange: (direction: ImpactDirection) => void;
  impactDepth: number;
  onImpactDepthChange: (depth: number) => void;
  maxImpactDepth: number;
  onRunImpact: () => void;

  path: AsyncActionState<DependencyPath>;
  pathTarget: GraphNode | null;
  onSetPathTarget: (node: GraphNode | null) => void;
  pathDepth: number;
  onPathDepthChange: (depth: number) => void;
  maxPathDepth: number;
  canRunPath: boolean;
  onRunPath: () => void;
}

export function NodeIntelligencePanel(props: NodeIntelligencePanelProps) {
  const { selectedNode, activeTab, onTabChange, onSelectNode } = props;

  if (!selectedNode) {
    return (
      <p className="py-3 text-sm text-neutral-500">
        Select a node in the graph to explore its dependencies, dependents, impact, and paths.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Selected node views">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => onTabChange(tab.id)}
              className={
                "rounded-md px-2.5 py-1 text-xs " +
                (activeTab === tab.id
                  ? "bg-neutral-100 font-medium text-neutral-900"
                  : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700")
              }
            >
              {tab.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => props.onSetPathTarget(selectedNode)}
          className="rounded-md bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-700"
        >
          Set as path target
        </button>
      </div>

      {props.pathTarget && activeTab !== "path" && (
        <p className="text-xs text-neutral-600">
          Path target pinned: {graphNodeLabel(props.pathTarget)}
        </p>
      )}

      {activeTab === "overview" && (
        <NodeDetailsPanel
          node={selectedNode}
          neighbors={props.neighbors}
          onSelectNode={onSelectNode}
        />
      )}

      {activeTab === "dependencies" && (
        <NeighborList
          state={props.dependencies}
          loadingMessage="Loading dependencies…"
          emptyMessage="This node depends on nothing in the projected graph."
          onSelectNode={onSelectNode}
        />
      )}

      {activeTab === "dependents" && (
        <NeighborList
          state={props.dependents}
          loadingMessage="Loading dependents…"
          emptyMessage="Nothing in the projected graph depends on this node."
          onSelectNode={onSelectNode}
        />
      )}

      {activeTab === "impact" && (
        <ImpactSection
          state={props.impact}
          direction={props.impactDirection}
          onDirectionChange={props.onImpactDirectionChange}
          depth={props.impactDepth}
          onDepthChange={props.onImpactDepthChange}
          maxDepth={props.maxImpactDepth}
          onRun={props.onRunImpact}
          onSelectNode={onSelectNode}
        />
      )}

      {activeTab === "path" && (
        <PathSection
          state={props.path}
          source={selectedNode}
          target={props.pathTarget}
          onClearTarget={() => props.onSetPathTarget(null)}
          depth={props.pathDepth}
          onDepthChange={props.onPathDepthChange}
          maxDepth={props.maxPathDepth}
          canRun={props.canRunPath}
          onRun={props.onRunPath}
          onSelectNode={onSelectNode}
        />
      )}
    </div>
  );
}
