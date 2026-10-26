import { API_BASE_URL, apiRequest } from './client'
import type { AnalysisState, AnalyzeResponse } from '../types/api'

export function getAnalysisState(
  repositoryId: string,
  signal?: AbortSignal,
): Promise<AnalysisState> {
  return apiRequest<AnalysisState>(`/repositories/${repositoryId}/analysis`, { signal })
}

export function triggerAnalysis(
  repositoryId: string,
  force: boolean,
): Promise<AnalyzeResponse> {
  return apiRequest<AnalyzeResponse>(`/repositories/${repositoryId}/analyze`, {
    method: 'POST',
    json: { force },
  })
}

/** The raw SSE endpoint URL — used by `useAnalysisProgress`, which owns
 * the `EventSource` lifecycle directly (EventSource has no fetch-like
 * abstraction, so it doesn't go through `apiRequest`). */
export function analysisStreamUrl(repositoryId: string): string {
  return `${API_BASE_URL}/repositories/${repositoryId}/analysis/stream`
}
