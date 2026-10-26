import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../app/router'
import * as analysisApi from '../../api/analysis'
import * as graphApi from '../../api/graph'
import * as healthApi from '../../api/health'
import * as impactApi from '../../api/impact'
import * as repositoriesApi from '../../api/repositories'
import { SourceViewerProvider } from '../../features/source/SourceViewerContext'
import type {
  AnalysisState,
  GraphNode,
  GraphSubgraph,
  ImpactAnalysisResult,
  ReadinessResponse,
  Repository,
} from '../../types/api'

vi.mock('../../api/repositories')
vi.mock('../../api/analysis')
vi.mock('../../api/health')
vi.mock('../../api/graph')
vi.mock('../../api/impact')

// Cytoscape-backed canvases are mocked at the component boundary in both
// the graph page and the impact page — same rationale as their
// standalone page tests.
vi.mock('../../features/graph/GraphCanvas', () => ({
  GraphCanvas: (props: { subgraph: GraphSubgraph; onSelectNode: (id: string) => void }) => (
    <button data-testid="mock-graph-canvas" onClick={() => props.onSelectNode('node-2')}>
      {props.subgraph.nodes.length} nodes
    </button>
  ),
}))
vi.mock('../../features/impact/ImpactGraph', () => ({
  ImpactGraph: () => <div data-testid="mock-impact-graph" />,
}))

const mockedRepositories = vi.mocked(repositoriesApi)
const mockedAnalysis = vi.mocked(analysisApi)
const mockedHealth = vi.mocked(healthApi)
const mockedGraph = vi.mocked(graphApi)
const mockedImpact = vi.mocked(impactApi)

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
    repository_id: 'repo-1',
    name: 'demo-python-app',
    source_type: 'zip_upload',
    source_location: 'demo.zip',
    status: 'ready',
    default_branch: null,
    commit_sha: null,
    file_count: 20,
    error_message: null,
    file_stats: null,
    created_at: null,
    last_indexed_at: null,
  }
}

function analysisState(): AnalysisState {
  return {
    repository_id: 'repo-1',
    overall_status: 'READY',
    parser_status: 'READY',
    graph_status: 'READY',
    vector_status: 'READY',
    current_stage: 'DONE',
    progress_percentage: 100,
    job_id: null,
    files_total: 20,
    files_processed: 20,
    files_failed: 0,
    graph_node_count: 30,
    graph_relationship_count: 40,
    vector_chunk_count: 50,
    warnings: [],
    errors: [],
    started_at: null,
    updated_at: '2026-08-14T00:00:00Z',
    completed_at: '2026-08-14T00:00:00Z',
    graph_updated_at: null,
    vector_updated_at: null,
    repository_revision: 'rev1',
    graph_current: true,
    vector_current: true,
    parse_duration_ms: null,
    graph_build_duration_ms: null,
    vector_index_duration_ms: null,
    total_duration_ms: null,
  }
}

function loginNode(): GraphNode {
  return {
    id: 'node-2',
    repository_id: 'repo-1',
    label: 'Function',
    name: 'login',
    qualified_name: 'app.auth.login',
    file_path: 'app/auth.py',
    start_line: 10,
    end_line: 20,
    properties: {},
  }
}

function subgraph(): GraphSubgraph {
  return {
    nodes: [loginNode()],
    edges: [],
    truncated: false,
    traversal_depth: 2,
    result_limit: 300,
  }
}

function impactResult(): ImpactAnalysisResult {
  return {
    repository_id: 'repo-1',
    target: {
      symbol_id: 'node-2',
      qualified_name: 'app.auth.login',
      name: 'login',
      target_type: 'FUNCTION',
      file_path: 'app/auth.py',
      start_line: 10,
      end_line: 20,
    },
    risk_score: 0.4,
    risk_level: 'MEDIUM',
    risk_signals: [],
    direct_callers: [],
    transitive_dependents: [],
    downstream_dependencies: [],
    affected_endpoints: [],
    affected_files: [],
    affected_modules: [],
    inheritance_impacts: [],
    inheriting_classes: [],
    base_classes: [],
    related_tests: [],
    test_relationship_status: 'UNKNOWN',
    traversal_depth: 2,
    total_impacted_symbols: 0,
    truncated: false,
    limitations: [],
    diagnostics: {
      analysis_duration_ms: 5,
      nodes_visited: 1,
      edges_traversed: 0,
      paths_examined: 0,
      cycles_detected: 0,
      truncated_reason: null,
    },
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

/** End-to-end workflow: select a node on the graph page and jump
 * straight to its change-impact analysis — see Prompt 11 "Frontend
 * Integration Tests" and "Graph Node Selection: Analyze Impact". */
describe('Integration: select a graph node and analyze its impact', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHealth.getReadiness.mockResolvedValue(readyReadiness())
    mockedRepositories.getRepository.mockResolvedValue(repository())
    mockedAnalysis.getAnalysisState.mockResolvedValue(analysisState())
    mockedGraph.getRepositoryGraph.mockResolvedValue(subgraph())
    mockedGraph.getSymbol.mockResolvedValue(loginNode())
    mockedImpact.getImpactAnalysis.mockResolvedValue(impactResult())
  })

  it('navigates from a selected graph node to its impact analysis page', async () => {
    renderApp('/repositories/repo-1/graph')

    fireEvent.click(await screen.findByTestId('mock-graph-canvas'))
    fireEvent.click(await screen.findByRole('button', { name: 'Analyze Impact' }))

    expect(await screen.findByText('Structural Change-Impact Risk')).toBeInTheDocument()
    expect(mockedImpact.getImpactAnalysis).toHaveBeenCalledWith('repo-1', 'node-2')
    expect(screen.getByText('app.auth.login')).toBeInTheDocument()
  })
})
