import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as analysisApi from '../../api/analysis'
import type { AnalysisState } from '../../types/api'
import { useAnalysisProgress } from './useAnalysisProgress'

vi.mock('../../api/analysis')
const mockedAnalysis = vi.mocked(analysisApi)

class FakeEventSource {
  static instances: FakeEventSource[] = []
  closed = false
  private listeners: Record<string, ((event: MessageEvent) => void)[]> = {}

  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, callback: (event: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(callback)
  }

  close() {
    this.closed = true
  }

  emit(type: string, data?: unknown) {
    const event = { data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent
    for (const callback of this.listeners[type] ?? []) callback(event)
  }
}

function baseState(overrides: Partial<AnalysisState> = {}): AnalysisState {
  return {
    repository_id: 'repo-1',
    overall_status: 'RUNNING',
    parser_status: 'RUNNING',
    graph_status: 'NOT_STARTED',
    vector_status: 'NOT_STARTED',
    current_stage: 'PARSE',
    progress_percentage: 10,
    job_id: 'job-1',
    files_total: 10,
    files_processed: 1,
    files_failed: 0,
    graph_node_count: null,
    graph_relationship_count: null,
    vector_chunk_count: null,
    warnings: [],
    errors: [],
    started_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:00:01Z',
    completed_at: null,
    graph_updated_at: null,
    vector_updated_at: null,
    repository_revision: 'rev1',
    graph_current: false,
    vector_current: false,
    parse_duration_ms: null,
    graph_build_duration_ms: null,
    vector_index_duration_ms: null,
    total_duration_ms: null,
    ...overrides,
  }
}

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('useAnalysisProgress', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    mockedAnalysis.analysisStreamUrl.mockReturnValue('http://test/stream')
  })

  it('does not open an SSE connection once the analysis is already terminal', async () => {
    mockedAnalysis.getAnalysisState.mockResolvedValue(baseState({ overall_status: 'READY' }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderHook(() => useAnalysisProgress('repo-1'), {
      wrapper: wrapper(queryClient),
    })

    await waitFor(() => expect(result.current.data?.overall_status).toBe('READY'))
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('opens exactly one SSE connection while running, and applies progress events', async () => {
    mockedAnalysis.getAnalysisState.mockResolvedValue(baseState())
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderHook(() => useAnalysisProgress('repo-1'), {
      wrapper: wrapper(queryClient),
    })

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    expect(FakeEventSource.instances[0].url).toBe('http://test/stream')

    FakeEventSource.instances[0].emit('progress', { progress_percentage: 55 })

    await waitFor(() => expect(result.current.data?.progress_percentage).toBe(55))
    // Still only one stream — no duplicate connection was opened.
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('closes the stream and invalidates queries on a completed event', async () => {
    mockedAnalysis.getAnalysisState.mockResolvedValue(baseState())
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    renderHook(() => useAnalysisProgress('repo-1'), { wrapper: wrapper(queryClient) })

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = FakeEventSource.instances[0]
    source.emit('completed', { overall_status: 'READY', progress_percentage: 100 })

    await waitFor(() => expect(source.closed).toBe(true))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['analysis', 'repo-1'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['repository', 'repo-1'] })
  })

  it('closes the SSE connection cleanly on unmount', async () => {
    mockedAnalysis.getAnalysisState.mockResolvedValue(baseState())
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { unmount } = renderHook(() => useAnalysisProgress('repo-1'), {
      wrapper: wrapper(queryClient),
    })

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = FakeEventSource.instances[0]
    expect(source.closed).toBe(false)

    unmount()

    expect(source.closed).toBe(true)
  })
})
