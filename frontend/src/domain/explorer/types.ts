/**
 * Explorer domain types.
 *
 * Purpose:       Mirror the backend's `ParsedFileResponse`, `SymbolResponse`,
 *                `ParameterResponse`, and `ParseErrorResponse` wire contracts.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: Keeps "what a parsed file / symbol / parse error looks like"
 *                independent of how it is fetched or displayed, matching the
 *                domain layer's role on the backend (see domain/parsing/entities.py).
 * Depended on by: infrastructure/api/explorerApi.ts,
 *                 application/explorer/useRepositoryExplorer.ts,
 *                 presentation/explorer/*.
 */

/**
 * Mirrors backend `SymbolKind` — the complete set the API accepts for its `kind`
 * filter. Exported as an array too so the filter UI cannot drift from it.
 */
export type SymbolKind = "function" | "class" | "method";

export const SYMBOL_KINDS: readonly SymbolKind[] = ["function", "class", "method"];

export interface ParsedFile {
  id: string;
  repositoryId: string;
  path: string;
  language: string;
  hasSyntaxErrors: boolean;
  symbolCount: number;
  importCount: number;
}

export interface SymbolParameter {
  name: string;
  position: number;
  annotation: string | null;
  defaultValue: string | null;
}

/**
 * Named `CodeSymbol` rather than `Symbol` to avoid shadowing the JavaScript
 * built-in of that name.
 */
export interface CodeSymbol {
  id: string;
  kind: string;
  name: string;
  qualifiedName: string;
  startLine: number;
  endLine: number;
  startColumn: number | null;
  endColumn: number | null;
  parameters: SymbolParameter[];
  parentSymbolId: string | null;
}

/**
 * A parse failure. The backend returns no id for these, so lists must key on the
 * combination of fields rather than expect one.
 */
export interface ParseError {
  filePath: string;
  stage: string;
  message: string;
}
