import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../app/router'
import * as analysisApi from '../../api/analysis'
import * as healthApi from '../../api/health'
import * as repositoriesApi from '../../api/repositories'
import { SourceViewerProvider } from '../../features/source/SourceViewerContext'
import type { AnalysisState, ReadinessResponse, Repository } from '../../types/api'

vi.mock('../../api/repositories')
vi.mock('../../api/analysis')
vi.mock('../../api/health')

const mockedRepositories = vi.mocked(repositoriesApi)
const mockedAnalysis = vi.mocked(analysisApi)
const mockedHealth = vi.mocked(healthApi)

function readyReadiness(): ReadinessResponse {
  return {
    status: 'ready',
    dependencies: {
      database: { status: 'READY', detail: null, model: null, provider: null },
      neo4j: { status: 'READY', detail: null, model: null, provider: null },
      chroma: { status: 'READY', detail: null, model: null, provider: null },
      embedding_provider: { status: 'READY', detail: null, model: null, provider: null },
    },
  }
}

function repository(): Repository {
  return {
    repository_id: 'repo-9',
    name: 'cloned-project',
    source_type: 'git_url',
    source_location: 'https://github.com/example/demo.git',
    status: 'ready',
    default_branch: 'main',
    commit_sha: 'abcdef1234567890',
    file_count: 12,
    error_message: null,
    file_stats: null,
    created_at: '2026-08-14T00:00:00Z',
    last_indexed_at: null,
  }
}

function analysisState(): AnalysisState {
  return {
    repository_id: 'repo-9',
    overall_status: 'READY',
    parser_status: 'READY',
    graph_status: 'READY',
    vector_status: 'READY',
    current_stage: 'DONE',
    progress_percentage: 100,
    job_id: 'job-1',
    files_total: 12,
    files_processed: 12,
    files_failed: 0,
    graph_node_count: 30,
    graph_relationship_count: 40,
    vector_chunk_count: 50,
    warnings: [],
    errors: [],
    started_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:01:00Z',
    completed_at: '2026-08-14T00:01:00Z',
    graph_updated_at: '2026-08-14T00:01:00Z',
    vector_updated_at: '2026-08-14T00:01:00Z',
    repository_revision: 'rev1',
    graph_current: true,
    vector_current: true,
    parse_duration_ms: 100,
    graph_build_duration_ms: 200,
    vector_index_duration_ms: 300,
    total_duration_ms: 600,
  }
}

function renderApp(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <SourceViewerProvider>
          <AppRoutes />
        </SourceViewerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** End-to-end workflow: import a repository via the dashboard dialog and
 * land on its overview page with real analysis status showing — see
 * Prompt 11 "Frontend Integration Tests". */
describe('Integration: import a repository and land on its overview page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHealth.getReadiness.mockResolvedValue(readyReadiness())
    mockedRepositories.listRepositories.mockResolvedValue([])
    mockedRepositories.cloneRepository.mockResolvedValue(repository())
    mockedRepositories.getRepository.mockResolvedValue(repository())
    mockedAnalysis.getAnalysisState.mockResolvedValue(analysisState())
  })

  it('imports via Clone Git, navigates to the new repository, and shows its status', async () => {
    renderApp('/')

    expect(await screen.findByText('No repositories yet')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Import Repository' })[0])
    fireEvent.click(await screen.findByRole('button', { name: 'Clone Git Repository' }))
    fireEvent.change(screen.getByLabelText('Repository name'), { target: { value: 'cloned-project' } })
    fireEvent.change(screen.getByPlaceholderText('https://github.com/example/project.git'), {
      target: { value: 'https://github.com/example/demo.git' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() =>
      expect(mockedRepositories.cloneRepository).toHaveBeenCalledWith(
        'cloned-project',
        'https://github.com/example/demo.git',
      ),
    )

    // Landed on the repository overview page (not still on the dashboard).
    expect(await screen.findByRole('heading', { name: 'cloned-project' })).toBeInTheDocument()
    expect(screen.getAllByText('READY').length).toBeGreaterThan(0)
  })
})
