/**
 * Explorer API client.
 *
 * Purpose:       Read a parsed repository — its files, symbols, one symbol's
 *                details, and its parse errors — translating the wire format into
 *                domain types.
 * Responsibility: The four read endpoints of the parsing module. No orchestration.
 * Why it exists: Keeps every explorer request going through one module so query
 *                parameters are built in exactly one place.
 *
 * Contract notes, taken from the live OpenAPI schema rather than assumed:
 *   - `/files` and `/parse-errors` accept NO query parameters, so neither can be
 *     paginated or filtered server-side.
 *   - `/symbols` accepts only `kind`, `file_id`, `limit`, `offset`. No other filter
 *     exists, and the response is a bare array with no total count — so callers
 *     infer "there may be more" from a full page rather than a count.
 *   - `/symbols/{id}` returns the same `SymbolResponse` shape as the list rows.
 *
 * Depends on:    infrastructure/api/client.ts, wire.ts, domain/explorer/types.ts.
 * Depended on by: application/explorer/useRepositoryExplorer.ts.
 */

import { apiGet } from "@/infrastructure/api/client";
import { repositoryPath } from "@/infrastructure/api/wire";
import type {
  CodeSymbol,
  ParseError,
  ParsedFile,
  SymbolKind,
  SymbolParameter,
} from "@/domain/explorer/types";

interface ParsedFileDto {
  id: string;
  repository_id: string;
  path: string;
  language: string;
  has_syntax_errors: boolean;
  symbol_count: number;
  import_count: number;
}

interface ParameterDto {
  name: string;
  position: number;
  annotation: string | null;
  default_value: string | null;
}

interface SymbolDto {
  id: string;
  kind: string;
  name: string;
  qualified_name: string;
  start_line: number;
  end_line: number;
  start_column: number | null;
  end_column: number | null;
  parameters: ParameterDto[];
  parent_symbol_id: string | null;
}

interface ParseErrorDto {
  file_path: string;
  stage: string;
  message: string;
}

function toParsedFile(dto: ParsedFileDto): ParsedFile {
  return {
    id: dto.id,
    repositoryId: dto.repository_id,
    path: dto.path,
    language: dto.language,
    hasSyntaxErrors: dto.has_syntax_errors,
    symbolCount: dto.symbol_count,
    importCount: dto.import_count,
  };
}

function toParameter(dto: ParameterDto): SymbolParameter {
  return {
    name: dto.name,
    position: dto.position,
    annotation: dto.annotation,
    defaultValue: dto.default_value,
  };
}

function toSymbol(dto: SymbolDto): CodeSymbol {
  return {
    id: dto.id,
    kind: dto.kind,
    name: dto.name,
    qualifiedName: dto.qualified_name,
    startLine: dto.start_line,
    endLine: dto.end_line,
    startColumn: dto.start_column,
    endColumn: dto.end_column,
    parameters: dto.parameters.map(toParameter),
    parentSymbolId: dto.parent_symbol_id,
  };
}

/**
 * List every parsed file, sorted by path.
 *
 * The endpoint takes no ordering parameter, so the sort happens here to give the UI
 * a stable order across reloads. This is the whole file list — bounded by the
 * repository's size, and cheap because the endpoint returns counts rather than
 * nested symbols and imports.
 */
export async function fetchFiles(projectId: string, repositoryId: string): Promise<ParsedFile[]> {
  const dtos = await apiGet<ParsedFileDto[]>(`${repositoryPath(projectId, repositoryId)}/files`);
  return dtos.map(toParsedFile).sort((a, b) => a.path.localeCompare(b.path));
}

export interface SymbolQuery {
  kind?: SymbolKind;
  fileId?: string;
  limit: number;
  offset: number;
}

/** List symbols, passing only the four query parameters the backend accepts. */
export async function fetchSymbols(
  projectId: string,
  repositoryId: string,
  query: SymbolQuery,
): Promise<CodeSymbol[]> {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.kind) params.set("kind", query.kind);
  if (query.fileId) params.set("file_id", query.fileId);

  const dtos = await apiGet<SymbolDto[]>(
    `${repositoryPath(projectId, repositoryId)}/symbols?${params.toString()}`,
  );
  return dtos.map(toSymbol);
}

export async function fetchSymbol(
  projectId: string,
  repositoryId: string,
  symbolId: string,
): Promise<CodeSymbol> {
  return toSymbol(
    await apiGet<SymbolDto>(`${repositoryPath(projectId, repositoryId)}/symbols/${symbolId}`),
  );
}

export async function fetchParseErrors(
  projectId: string,
  repositoryId: string,
): Promise<ParseError[]> {
  const dtos = await apiGet<ParseErrorDto[]>(
    `${repositoryPath(projectId, repositoryId)}/parse-errors`,
  );
  return dtos.map((dto) => ({
    filePath: dto.file_path,
    stage: dto.stage,
    message: dto.message,
  }));
}
