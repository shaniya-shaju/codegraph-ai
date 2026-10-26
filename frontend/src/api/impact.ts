import { apiRequest } from './client'
import type { ImpactAnalysisResult, ImpactExplanationResponse } from '../types/api'

export interface ImpactQueryOptions {
  qualifiedName?: string
  maxDepth?: number
  maxNodes?: number
  includeDownstream?: boolean
  includeTests?: boolean
}

export function getImpactAnalysis(
  repositoryId: string,
  symbolId: string,
  options: ImpactQueryOptions = {},
  signal?: AbortSignal,
): Promise<ImpactAnalysisResult> {
  return apiRequest<ImpactAnalysisResult>(`/repositories/${repositoryId}/impact/${symbolId}`, {
    searchParams: {
      qualified_name: options.qualifiedName,
      max_depth: options.maxDepth,
      max_nodes: options.maxNodes,
      include_downstream: options.includeDownstream,
      include_tests: options.includeTests,
    },
    signal,
  })
}

export function explainImpact(
  repositoryId: string,
  symbolId: string,
  options: ImpactQueryOptions = {},
): Promise<ImpactExplanationResponse> {
  return apiRequest<ImpactExplanationResponse>(
    `/repositories/${repositoryId}/impact/${symbolId}/explain`,
    {
      method: 'POST',
      searchParams: {
        qualified_name: options.qualifiedName,
        max_depth: options.maxDepth,
        max_nodes: options.maxNodes,
        include_downstream: options.includeDownstream,
        include_tests: options.includeTests,
      },
      timeoutMs: 60_000,
    },
  )
}
