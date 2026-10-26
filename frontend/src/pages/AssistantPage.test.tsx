import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as graphApi from '../api/graph'
import * as healthApi from '../api/health'
import * as queryApi from '../api/query'
import { renderWithProviders } from '../tests/testUtils'
import type { QueryResponse, ReadinessResponse } from '../types/api'
import { AssistantPage } from './AssistantPage'

vi.mock('../api/query')
vi.mock('../api/health')
vi.mock('../api/graph')

const mockedQuery = vi.mocked(queryApi)
const mockedHealth = vi.mocked(healthApi)
const mockedGraph = vi.mocked(graphApi)

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

function answer(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    answer: 'AuthService.login validates credentials [1] and issues a session token [2].',
    citations: [
      {
        citation_id: 'c1',
        file_path: 'app/auth/service.py',
        start_line: 10,
        end_line: 20,
        symbol_id: 'sym-1',
        qualified_name: 'app.auth.service.AuthService.login',
        evidence_type: 'code_chunk',
      },
      {
        citation_id: 'c2',
        file_path: 'app/auth/tokens.py',
        start_line: 5,
        end_line: 8,
        symbol_id: 'sym-2',
        qualified_name: 'app.auth.tokens.issue',
        evidence_type: 'call_relationship',
      },
    ],
    confidence_level: 'HIGH',
    confidence_reason: 'Backed by direct source evidence.',
    retrieval_mode: 'hybrid',
    primary_intent: 'code_explanation',
    resolved_symbols: [],
    limitations: [],
    abstained: false,
    conversation_id: null,
    ...overrides,
  }
}

describe('AssistantPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHealth.getReadiness.mockResolvedValue(readyReadiness())
  })

  it('shows the suggested questions before any turn has been asked', async () => {
    renderWithProviders(<AssistantPage />, { route: '/repositories/repo-1/assistant', path: '/repositories/:repositoryId/assistant' })

    expect(await screen.findByText('Where is user authentication implemented?')).toBeInTheDocument()
  })

  it('asks a question, renders the answer with confidence and citations, and hides suggestions afterward', async () => {
    mockedQuery.askQuestion.mockResolvedValue(answer())
    renderWithProviders(<AssistantPage />, { route: '/repositories/repo-1/assistant', path: '/repositories/:repositoryId/assistant' })

    fireEvent.click(await screen.findByText('Explain AuthService.login in simple terms.'))

    await waitFor(() =>
      expect(mockedQuery.askQuestion).toHaveBeenCalledWith(
        'repo-1',
        'Explain AuthService.login in simple terms.',
        'hybrid',
        null,
      ),
    )

    expect(await screen.findByText('HIGH')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[1]' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '[2]' })).toBeInTheDocument()
    expect(screen.queryByText('Where is user authentication implemented?')).not.toBeInTheDocument()
  })

  it('shows abstention copy clearly instead of rendering citations when the backend abstains', async () => {
    mockedQuery.askQuestion.mockResolvedValue(
      answer({ abstained: true, answer: 'Not enough evidence in this repository.', citations: [] }),
    )
    renderWithProviders(<AssistantPage />, { route: '/repositories/repo-1/assistant', path: '/repositories/:repositoryId/assistant' })

    fireEvent.click(await screen.findByText('Where is user authentication implemented?'))

    expect(await screen.findByText('Insufficient repository evidence')).toBeInTheDocument()
    expect(screen.getByText('Not enough evidence in this repository.')).toBeInTheDocument()
  })

  it('opens the source viewer with the backend-supplied file/line when a citation marker is clicked', async () => {
    mockedQuery.askQuestion.mockResolvedValue(answer())
    mockedGraph.getSourceSnippet.mockResolvedValue({
      repository_id: 'repo-1',
      file_path: 'app/auth/service.py',
      start_line: 5,
      end_line: 25,
      total_lines: 40,
      content: 'def login():\n    pass\n',
      truncated: false,
    })
    renderWithProviders(<AssistantPage />, { route: '/repositories/repo-1/assistant', path: '/repositories/:repositoryId/assistant' })

    fireEvent.click(await screen.findByText('Explain AuthService.login in simple terms.'))
    fireEvent.click(await screen.findByRole('button', { name: '[1]' }))

    expect(await screen.findByRole('dialog', { name: /app\/auth\/service\.py/ })).toBeInTheDocument()
    await waitFor(() =>
      expect(mockedGraph.getSourceSnippet).toHaveBeenCalledWith('repo-1', 'app/auth/service.py', {
        startLine: 10,
        endLine: 20,
      }),
    )
  })

  it('disables the Graph retrieval mode with an explanation when the knowledge graph is unavailable', async () => {
    mockedHealth.getReadiness.mockResolvedValue({
      status: 'degraded',
      dependencies: {
        database: { status: 'READY', detail: null, model: null, provider: null },
        neo4j: { status: 'UNAVAILABLE', detail: null, model: null, provider: null },
        chroma: { status: 'READY', detail: null, model: null, provider: null },
        embedding_provider: { status: 'READY', detail: null, model: null, provider: null },
      },
    })
    renderWithProviders(<AssistantPage />, { route: '/repositories/repo-1/assistant', path: '/repositories/:repositoryId/assistant' })

    const graphButton = await screen.findByRole('radio', { name: 'Graph' })
    await waitFor(() => expect(graphButton).toBeDisabled())
    expect(graphButton).toHaveAttribute('title', 'Knowledge graph unavailable')
    expect(
      await screen.findByText('Knowledge graph unavailable. Semantic code search remains available.'),
    ).toBeInTheDocument()
  })
})
