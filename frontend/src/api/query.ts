import { API_BASE_URL, apiRequest } from './client'
import type { QueryResponse, RetrievalMode } from '../types/api'

export function askQuestion(
  repositoryId: string,
  question: string,
  retrievalMode: RetrievalMode,
  conversationId: string | null,
): Promise<QueryResponse> {
  return apiRequest<QueryResponse>(`/repositories/${repositoryId}/query`, {
    method: 'POST',
    json: {
      question,
      retrieval_mode: retrievalMode,
      conversation_id: conversationId ?? undefined,
    },
    timeoutMs: 60_000,
  })
}

/** The raw SSE query-stream URL — used by `useStreamingAnswer`, which
 * issues its own `fetch`/`POST` with a streaming body reader (browsers'
 * built-in `EventSource` only supports GET, so this endpoint is
 * consumed manually rather than through `EventSource`). */
export function queryStreamUrl(repositoryId: string): string {
  return `${API_BASE_URL}/repositories/${repositoryId}/query/stream`
}
