import { useQueryClient, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { analysisStreamUrl, getAnalysisState } from '../../api/analysis'
import type { AnalysisState } from '../../types/api'

const POLL_INTERVAL_MS = 3000
const TERMINAL_STATUSES = new Set(['READY', 'PARTIAL', 'FAILED', 'STALE'])

/** See Prompt 11 "SSE Handling": fetch persisted state; if RUNNING,
 * connect SSE; update UI from events; on disconnect, fall back to
 * polling; after completion, invalidate repository/statistics queries;
 * close SSE cleanly on unmount; never open more than one stream for the
 * same repository at a time. */
export function useAnalysisProgress(repositoryId: string | undefined) {
  const queryClient = useQueryClient()
  const [streamConnected, setStreamConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const query = useQuery({
    queryKey: ['analysis', repositoryId],
    queryFn: ({ signal }) => getAnalysisState(repositoryId as string, signal),
    enabled: Boolean(repositoryId),
    // Polling fallback — only actually polls while running AND the SSE
    // stream isn't connected (see the effect below), so a healthy SSE
    // connection doesn't also poll redundantly.
    refetchInterval: (query) => {
      const data = query.state.data as AnalysisState | undefined
      if (!data || TERMINAL_STATUSES.has(data.overall_status)) return false
      return streamConnected ? false : POLL_INTERVAL_MS
    },
  })

  const overallStatus = query.data?.overall_status

  useEffect(() => {
    if (!repositoryId || !overallStatus || TERMINAL_STATUSES.has(overallStatus)) {
      return
    }
    if (typeof EventSource === 'undefined') {
      // No SSE support in this environment — polling above covers it.
      return
    }

    const source = new EventSource(analysisStreamUrl(repositoryId))
    eventSourceRef.current = source

    function applyEvent(raw: MessageEvent<string>) {
      try {
        const payload = JSON.parse(raw.data) as Partial<AnalysisState> & {
          progress_percentage?: number
        }
        queryClient.setQueryData<AnalysisState | undefined>(
          ['analysis', repositoryId],
          (previous) => (previous ? { ...previous, ...payload } : previous),
        )
      } catch {
        // Malformed event payload — ignore it, the next poll will still
        // pick up the real persisted state.
      }
    }

    source.addEventListener('open', () => setStreamConnected(true))
    source.addEventListener('progress', applyEvent as EventListener)
    source.addEventListener('completed', (event) => {
      applyEvent(event as MessageEvent<string>)
      void queryClient.invalidateQueries({ queryKey: ['analysis', repositoryId] })
      void queryClient.invalidateQueries({ queryKey: ['repository', repositoryId] })
      source.close()
    })
    source.addEventListener('failed', (event) => {
      applyEvent(event as MessageEvent<string>)
      void queryClient.invalidateQueries({ queryKey: ['analysis', repositoryId] })
      source.close()
    })
    source.addEventListener('error', () => {
      // Fall back to polling — see refetchInterval above, which resumes
      // once streamConnected flips back to false.
      setStreamConnected(false)
      source.close()
    })

    return () => {
      source.close()
      eventSourceRef.current = null
      setStreamConnected(false)
    }
  }, [repositoryId, overallStatus, queryClient])

  return query
}
