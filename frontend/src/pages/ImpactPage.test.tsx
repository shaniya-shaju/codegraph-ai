import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as graphApi from '../api/graph'
import * as healthApi from '../api/health'
import * as impactApi from '../api/impact'
import { renderWithProviders } from '../tests/testUtils'
import type { ImpactAnalysisResult, ReadinessResponse } from '../types/api'
import { ImpactPage } from './ImpactPage'

vi.mock('../api/impact')
vi.mock('../api/health')
vi.mock('../api/graph')

// Impact Graph renders Cytoscape directly — mocked at the component
// boundary, same rationale as GraphPage's GraphCanvas mock.
vi.mock('../features/impact/ImpactGraph', () => ({
  ImpactGraph: () => <div data-testid="mock-impact-graph" />,
}))

const mockedImpact = vi.mocked(impactApi)
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

function impactResult(overrides: Partial<ImpactAnalysisResult> = {}): ImpactAnalysisResult {
  return {
    repository_id: 'repo-1',
    target: {
      symbol_id: 'sym-1',
      qualified_name: 'app.auth.service.AuthService.login',
      name: 'login',
      target_type: 'METHOD',
      file_path: 'app/auth/service.py',
      start_line: 10,
      end_line: 30,
    },
    risk_score: 0.72,
    risk_level: 'HIGH',
    risk_signals: [
      {
        signal_type: 'DIRECT_CALLER_COUNT',
        raw_value: 6,
        normalized_value: 0.6,
        contribution: 0.3,
        explanation: '6 symbols directly call this function.',
      },
    ],
    direct_callers: [
      {
        symbol_id: 'sym-2',
        qualified_name: 'app.api.routes.login_handler',
        symbol_type: 'FUNCTION',
        file_path: 'app/api/routes.py',
        start_line: 5,
        end_line: 15,
        impact_type: 'DIRECT_CALLER',
        distance: 1,
        reason: 'Directly calls AuthService.login.',
        path: ['app.api.routes.login_handler', 'app.auth.service.AuthService.login'],
        relationship_path: ['CALLS'],
      },
    ],
    transitive_dependents: [],
    downstream_dependencies: [],
    affected_endpoints: [
      {
        endpoint_id: 'ep-1',
        http_method: 'POST',
        route_path: '/login',
        handler_symbol_id: 'sym-2',
        handler_qualified_name: 'app.api.routes.login_handler',
        distance_from_target: 1,
        impact_reason: 'Handler calls the changed symbol.',
      },
    ],
    affected_files: [
      {
        file_path: 'app/api/routes.py',
        affected_symbol_count: 1,
        minimum_distance: 1,
        impact_types: ['DIRECT_CALLER'],
        impacted_symbol_ids: ['sym-2'],
      },
    ],
    affected_modules: [],
    inheritance_impacts: [],
    inheriting_classes: [],
    base_classes: [],
    related_tests: [],
    test_relationship_status: 'NO_KNOWN_TEST_REFERENCES',
    traversal_depth: 3,
    total_impacted_symbols: 2,
    truncated: false,
    limitations: ['Only Python symbols are tracked.'],
    diagnostics: {
      analysis_duration_ms: 12,
      nodes_visited: 10,
      edges_traversed: 9,
      paths_examined: 3,
      cycles_detected: 0,
      truncated_reason: null,
    },
    ...overrides,
  }
}

describe('ImpactPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHealth.getReadiness.mockResolvedValue(readyReadiness())
    mockedGraph.searchSymbols.mockResolvedValue([])
  })

  it('prompts for a symbol via search when no symbolId is in the URL', async () => {
    renderWithProviders(<ImpactPage />, {
      route: '/repositories/repo-1/impact',
      path: '/repositories/:repositoryId/impact',
    })

    expect(
      await screen.findByText(/Search for a function, method, class, or API endpoint/),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Search symbols')).toBeInTheDocument()
    expect(mockedImpact.getImpactAnalysis).not.toHaveBeenCalled()
  })

  it('renders the risk summary using the required "Structural Change-Impact Risk" label, never "Failure Risk"', async () => {
    mockedImpact.getImpactAnalysis.mockResolvedValue(impactResult())
    renderWithProviders(<ImpactPage />, {
      route: '/repositories/repo-1/impact/sym-1',
      path: '/repositories/:repositoryId/impact/:symbolId',
    })

    expect(await screen.findByText('Structural Change-Impact Risk')).toBeInTheDocument()
    expect(screen.queryByText(/Failure Risk/)).not.toBeInTheDocument()
    expect(screen.getByText('HIGH', { exact: false })).toBeInTheDocument()
  })

  it('renders affected APIs, affected files, and upstream dependents straight from backend data', async () => {
    mockedImpact.getImpactAnalysis.mockResolvedValue(impactResult())
    renderWithProviders(<ImpactPage />, {
      route: '/repositories/repo-1/impact/sym-1',
      path: '/repositories/:repositoryId/impact/:symbolId',
    })

    expect(await screen.findByText('/login')).toBeInTheDocument()
    expect(screen.getByText('app/api/routes.py')).toBeInTheDocument()
    expect(screen.getByText('app.api.routes.login_handler')).toBeInTheDocument()
    expect(screen.getByText('6 symbols directly call this function.')).toBeInTheDocument()
  })

  it('shows an error state with retry when the impact request fails', async () => {
    mockedImpact.getImpactAnalysis.mockRejectedValue(new Error('boom'))
    renderWithProviders(<ImpactPage />, {
      route: '/repositories/repo-1/impact/sym-1',
      path: '/repositories/:repositoryId/impact/:symbolId',
    })

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('shows a degraded-state message and never calls the impact API when Neo4j is unavailable', async () => {
    mockedHealth.getReadiness.mockResolvedValue({
      status: 'degraded',
      dependencies: {
        database: { status: 'READY', detail: null, model: null, provider: null },
        neo4j: { status: 'UNAVAILABLE', detail: null, model: null, provider: null },
        chroma: { status: 'READY', detail: null, model: null, provider: null },
        embedding_provider: { status: 'READY', detail: null, model: null, provider: null },
      },
    })
    renderWithProviders(<ImpactPage />, {
      route: '/repositories/repo-1/impact/sym-1',
      path: '/repositories/:repositoryId/impact/:symbolId',
    })

    expect(await screen.findByText(/Knowledge graph unavailable/)).toBeInTheDocument()
    await waitFor(() => expect(mockedImpact.getImpactAnalysis).not.toHaveBeenCalled())
  })
})
