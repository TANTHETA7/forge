import { describe, expect, it } from "vitest";

import type { FileGraphNode, GraphNode, SymbolGraphNode } from "@/domain/graph/types";
import { layoutGraph } from "@/presentation/graph/graphLayout";

const file = (id: string, path: string): FileGraphNode => ({
  id,
  kind: "file",
  repositoryId: "r",
  path,
  language: "python",
  hasSyntaxErrors: false,
});

const symbol = (id: string, name: string, fileId: string, startLine: number): SymbolGraphNode => ({
  id,
  kind: "symbol",
  repositoryId: "r",
  name,
  qualifiedName: name,
  symbolKind: "function",
  fileId,
  startLine,
  endLine: startLine + 1,
});

const REPO: GraphNode = {
  id: "n-repo",
  kind: "repository",
  repositoryId: "r",
  displayName: "repo",
  projectId: "p",
  projectedAt: null,
};

const xOf = (positioned: ReturnType<typeof layoutGraph>, id: string) =>
  positioned.find((p) => p.node.id === id)!.x;

describe("layoutGraph", () => {
  it("returns nothing for an empty graph", () => {
    expect(layoutGraph([])).toEqual([]);
  });

  it("positions each kind in its own column, in containment order", () => {
    const positioned = layoutGraph([REPO, file("f1", "a.py"), symbol("s1", "go", "f1", 1)]);

    expect(xOf(positioned, "n-repo")).toBeLessThan(xOf(positioned, "f1"));
    expect(xOf(positioned, "f1")).toBeLessThan(xOf(positioned, "s1"));
  });

  it("gives every node a position and keeps them all", () => {
    const nodes = [REPO, file("f1", "b.py"), file("f2", "a.py"), symbol("s1", "go", "f1", 1)];

    const positioned = layoutGraph(nodes);

    expect(positioned).toHaveLength(4);
    expect(new Set(positioned.map((p) => p.node.id))).toEqual(
      new Set(["n-repo", "f1", "f2", "s1"]),
    );
  });

  it("is deterministic — input order does not affect output", () => {
    const nodes = [file("f2", "b.py"), REPO, symbol("s1", "go", "f1", 1), file("f1", "a.py")];
    const shuffled = [symbol("s1", "go", "f1", 1), file("f1", "a.py"), file("f2", "b.py"), REPO];

    const first = layoutGraph(nodes);
    const second = layoutGraph(shuffled);

    const key = (p: ReturnType<typeof layoutGraph>[number]) => `${p.node.id}@${p.x},${p.y}`;
    expect(first.map(key).sort()).toEqual(second.map(key).sort());
  });

  it("orders files by path so the column is stable and readable", () => {
    const positioned = layoutGraph([file("f2", "zzz.py"), file("f1", "aaa.py")]);

    const aaa = positioned.find((p) => p.node.id === "f1")!;
    const zzz = positioned.find((p) => p.node.id === "f2")!;
    expect(aaa.y).toBeLessThan(zzz.y);
  });

  it("groups symbols by their file, then by line", () => {
    const positioned = layoutGraph([
      symbol("s3", "c", "fileB", 1),
      symbol("s2", "b", "fileA", 20),
      symbol("s1", "a", "fileA", 5),
    ]);

    const y = (id: string) => positioned.find((p) => p.node.id === id)!.y;
    // fileA's symbols stay together and in line order, ahead of fileB's.
    expect(y("s1")).toBeLessThan(y("s2"));
    expect(y("s2")).toBeLessThan(y("s3"));
  });

  it("does not stack two nodes of the same kind at the same point", () => {
    const nodes = Array.from({ length: 30 }, (_, i) => file(`f${i}`, `file${i}.py`));

    const positioned = layoutGraph(nodes);

    const points = positioned.map((p) => `${p.x},${p.y}`);
    expect(new Set(points).size).toBe(30);
  });

  it("puts an unrecognized kind in its own column rather than dropping it", () => {
    const positioned = layoutGraph([
      REPO,
      { id: "n-x", kind: "unknown", repositoryId: "r", rawKind: "package" },
    ]);

    expect(positioned).toHaveLength(2);
    expect(xOf(positioned, "n-x")).toBeGreaterThan(xOf(positioned, "n-repo"));
  });
});

describe("layoutGraph column wrapping", () => {
  /** A tall column must wrap, or it becomes an unreadable strip at any usable zoom. */
  const manySymbols = (count: number) =>
    Array.from({ length: count }, (_, i) =>
      symbol(`s${i}`, `sym${String(i).padStart(3, "0")}`, "f1", i),
    );

  it("keeps a short column in a single sub-column", () => {
    const positioned = layoutGraph(manySymbols(10));

    expect(new Set(positioned.map((p) => p.x)).size).toBe(1);
  });

  it("wraps a tall column into several sub-columns", () => {
    const positioned = layoutGraph(manySymbols(40));

    const columns = new Set(positioned.map((p) => p.x));
    expect(columns.size).toBeGreaterThan(1);
    // Bounded height rather than one 40-row strip.
    const rowsPerColumn = [...columns].map(
      (x) => positioned.filter((p) => p.x === x).length,
    );
    expect(Math.max(...rowsPerColumn)).toBeLessThanOrEqual(14);
  });

  it("does not let a wrapped column collide with the next kind's column", () => {
    const nodes: GraphNode[] = [REPO, file("f1", "a.py"), ...manySymbols(40)];

    const positioned = layoutGraph(nodes);

    const symbolXs = positioned.filter((p) => p.node.kind === "symbol").map((p) => p.x);
    const fileX = xOf(positioned, "f1");
    // Every symbol sub-column sits to the right of the file column.
    expect(Math.min(...symbolXs)).toBeGreaterThan(fileX);
  });

  it("still gives every node a unique position when wrapped", () => {
    const positioned = layoutGraph(manySymbols(40));

    expect(new Set(positioned.map((p) => `${p.x},${p.y}`)).size).toBe(40);
  });

  it("remains deterministic when wrapping", () => {
    const nodes = manySymbols(40);
    const key = (p: ReturnType<typeof layoutGraph>[number]) => `${p.node.id}@${p.x},${p.y}`;

    const first = layoutGraph(nodes).map(key).sort();
    const second = layoutGraph([...nodes].reverse()).map(key).sort();

    expect(first).toEqual(second);
  });
});
