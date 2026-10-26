import { apiRequest } from './client'
import type {
  GraphNode,
  GraphStatistics,
  GraphSubgraph,
  SourceSnippet,
  SymbolSearchResult,
} from '../types/api'

export function getRepositoryGraph(
  repositoryId: string,
  options: { rootSymbolId?: string; depth?: number; maxNodes?: number } = {},
): Promise<GraphSubgraph> {
  return apiRequest<GraphSubgraph>(`/repositories/${repositoryId}/graph`, {
    searchParams: {
      root_symbol_id: options.rootSymbolId,
      depth: options.depth,
      max_nodes: options.maxNodes,
    },
  })
}

export function getGraphStatistics(repositoryId: string): Promise<GraphStatistics> {
  return apiRequest<GraphStatistics>(`/repositories/${repositoryId}/graph/statistics`)
}

export function searchSymbols(
  repositoryId: string,
  query: string,
  options: { symbolType?: string; filePath?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SymbolSearchResult[]> {
  return apiRequest<SymbolSearchResult[]>(`/repositories/${repositoryId}/symbols/search`, {
    searchParams: {
      q: query,
      symbol_type: options.symbolType,
      file_path: options.filePath,
      limit: options.limit,
    },
    signal,
  })
}

export function getSymbol(repositoryId: string, symbolId: string): Promise<GraphNode> {
  return apiRequest<GraphNode>(`/repositories/${repositoryId}/symbols/${symbolId}`)
}

export function getSymbolNeighbors(
  repositoryId: string,
  symbolId: string,
  options: { depth?: number; limit?: number } = {},
): Promise<GraphSubgraph> {
  return apiRequest<GraphSubgraph>(
    `/repositories/${repositoryId}/symbols/${symbolId}/neighbors`,
    { searchParams: { depth: options.depth, limit: options.limit } },
  )
}

export function getSymbolCallers(
  repositoryId: string,
  symbolId: string,
  limit?: number,
): Promise<GraphSubgraph> {
  return apiRequest<GraphSubgraph>(`/repositories/${repositoryId}/symbols/${symbolId}/callers`, {
    searchParams: { limit },
  })
}

export function getSymbolCallees(
  repositoryId: string,
  symbolId: string,
  limit?: number,
): Promise<GraphSubgraph> {
  return apiRequest<GraphSubgraph>(`/repositories/${repositoryId}/symbols/${symbolId}/callees`, {
    searchParams: { limit },
  })
}

export function getSymbolDependencies(
  repositoryId: string,
  symbolId: string,
  limit?: number,
): Promise<GraphSubgraph> {
  return apiRequest<GraphSubgraph>(
    `/repositories/${repositoryId}/symbols/${symbolId}/dependencies`,
    { searchParams: { limit } },
  )
}

export function getSourceSnippet(
  repositoryId: string,
  path: string,
  options: { startLine?: number; endLine?: number } = {},
): Promise<SourceSnippet> {
  return apiRequest<SourceSnippet>(`/repositories/${repositoryId}/files/source`, {
    searchParams: { path, start_line: options.startLine, end_line: options.endLine },
  })
}
