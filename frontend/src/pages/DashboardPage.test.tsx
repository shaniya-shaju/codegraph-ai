import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as analysisApi from '../api/analysis'
import * as repositoriesApi from '../api/repositories'
import { renderWithProviders } from '../tests/testUtils'
import type { Repository } from '../types/api'
import { DashboardPage } from './DashboardPage'

vi.mock('../api/repositories')
vi.mock('../api/analysis')

const mockedRepositories = vi.mocked(repositoriesApi)
const mockedAnalysis = vi.mocked(analysisApi)

function makeRepository(overrides: Partial<Repository> = {}): Repository {
  return {
    repository_id: 'repo-1',
    name: 'demo-python-app',
    source_type: 'zip_upload',
    source_location: 'demo-python-app.zip',
    status: 'ready',
    default_branch: null,
    commit_sha: null,
    file_count: 42,
    error_message: null,
    file_stats: null,
    created_at: '2026-08-01T00:00:00Z',
    last_indexed_at: '2026-08-01T00:05:00Z',
    ...overrides,
  }
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedAnalysis.getAnalysisState.mockRejectedValue(new Error('no analysis state in this test'))
  })

  it('shows a loading state before repositories resolve', () => {
    mockedRepositories.listRepositories.mockReturnValue(new Promise(() => {}))
    renderWithProviders(<DashboardPage />)
    expect(screen.getAllByTestId('skeleton-rows').length).toBeGreaterThan(0)
  })

  it('shows the required empty-state copy when there are no repositories', async () => {
    mockedRepositories.listRepositories.mockResolvedValue([])
    renderWithProviders(<DashboardPage />)

    expect(await screen.findByText('No repositories yet')).toBeInTheDocument()
    expect(
      screen.getByText('Upload a ZIP or clone a public Git repository to begin code analysis.'),
    ).toBeInTheDocument()
  })

  it('renders a card per repository once the list resolves', async () => {
    mockedRepositories.listRepositories.mockResolvedValue([
      makeRepository({ repository_id: 'repo-1', name: 'demo-python-app' }),
      makeRepository({ repository_id: 'repo-2', name: 'another-repo' }),
    ])
    renderWithProviders(<DashboardPage />)

    expect(await screen.findByText('demo-python-app')).toBeInTheDocument()
    expect(screen.getByText('another-repo')).toBeInTheDocument()
  })

  it('shows an error state with retry when the list fails to load', async () => {
    mockedRepositories.listRepositories.mockRejectedValue(new Error('network down'))
    renderWithProviders(<DashboardPage />)

    await waitFor(() => expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument())
  })

  it('opens the import dialog from the header button', async () => {
    mockedRepositories.listRepositories.mockResolvedValue([])
    renderWithProviders(<DashboardPage />)
    await screen.findByText('No repositories yet')

    const openButtons = screen.getAllByRole('button', { name: 'Import Repository' })
    fireEvent.click(openButtons[0])

    expect(await screen.findByRole('dialog', { name: 'Import Repository' })).toBeInTheDocument()
  })
})
