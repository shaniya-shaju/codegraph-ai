import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as graphApi from '../api/graph'
import * as healthApi from '../api/health'
import { renderWithProviders } from '../tests/testUtils'
import type { GraphNode, GraphSubgraph, ReadinessResponse } from '../types/api'
import { GraphPage } from './GraphPage'

vi.mock('../api/graph')
vi.mock('../api/health')

// GraphCanvas wraps Cytoscape directly — mocked at the component
// boundary per Prompt 11's own allowance ("Cytoscape itself may be
// mocked at component-boundary level where appropriate"), exposing just
// enough to drive selection from the test.
vi.mock('../features/graph/GraphCanvas', () => ({
  GraphCanvas: (props: { subgraph: GraphSubgraph; onSelectNode: (id: string) => void }) => (
    <button data-testid="mock-graph-canvas" onClick={() => props.onSelectNode('node-2')}>
      {props.subgraph.nodes.length} nodes
    </button>
  ),
}))

const mockedGraph = vi.mocked(graphApi)
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

function subgraph(): GraphSubgraph {
  return {
    nodes: [
      {
        id: 'node-1',
        repository_id: 'repo-1',
        label: 'Module',
        name: 'app',
        qualified_name: 'app',
        file_path: 'app/__init__.py',
        start_line: 1,
        end_line: 1,
        properties: {},
      },
      {
        id: 'node-2',
        repository_id: 'repo-1',
        label: 'Function',
        name: 'login',
        qualified_name: 'app.auth.login',
        file_path: 'app/auth.py',
        start_line: 10,
        end_line: 20,
        properties: { signature: 'def login(username, password):' },
      },
    ],
    edges: [
      {
        id: 'edge-1',
        repository_id: 'repo-1',
        source_id: 'node-1',
        target_id: 'node-2',
        relationship_type: 'CONTAINS',
        properties: {},
      },
    ],
    truncated: false,
    traversal_depth: 2,
    result_limit: 300,
  }
}

function node(): GraphNode {
  return subgraph().nodes[1]
}

describe('GraphPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedHealth.getReadiness.mockResolvedValue(readyReadiness())
    mockedGraph.getRepositoryGraph.mockResolvedValue(subgraph())
    mockedGraph.getSymbol.mockResolvedValue(node())
  })

  it('fetches and renders a bounded default subgraph', async () => {
    renderWithProviders(<GraphPage />, {
      route: '/repositories/repo-1/graph',
      path: '/repositories/:repositoryId/graph',
    })

    await waitFor(() =>
      expect(mockedGraph.getRepositoryGraph).toHaveBeenCalledWith('repo-1', {
        rootSymbolId: undefined,
        depth: 2,
      }),
    )
    expect(await screen.findByTestId('mock-graph-canvas')).toHaveTextContent('2 nodes')
  })

  it('shows the node detail panel with type-appropriate actions once a node is selected', async () => {
    renderWithProviders(<GraphPage />, {
      route: '/repositories/repo-1/graph',
      path: '/repositories/:repositoryId/graph',
    })

    fireEvent.click(await screen.findByTestId('mock-graph-canvas'))

    expect(await screen.findByText('app.auth.login')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View Source' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Callers' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Callees' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze Impact' })).toBeInTheDocument()
  })

  it('pushes a breadcrumb and fetches callers when "Show Callers" is used', async () => {
    mockedGraph.getSymbolCallers.mockResolvedValue({
      nodes: [node()],
      edges: [],
      truncated: false,
      traversal_depth: 1,
      result_limit: 300,
    })
    renderWithProviders(<GraphPage />, {
      route: '/repositories/repo-1/graph',
      path: '/repositories/:repositoryId/graph',
    })

    fireEvent.click(await screen.findByTestId('mock-graph-canvas'))
    fireEvent.click(await screen.findByRole('button', { name: 'Show Callers' }))

    await waitFor(() => expect(mockedGraph.getSymbolCallers).toHaveBeenCalledWith('repo-1', 'node-2'))
    expect(await screen.findByText('Callers of app.auth.login')).toBeInTheDocument()
  })

  it('shows a degraded-state message and never calls the graph API when Neo4j is unavailable', async () => {
    mockedHealth.getReadiness.mockResolvedValue({
      status: 'degraded',
      dependencies: {
        database: { status: 'READY', detail: null, model: null, provider: null },
        neo4j: { status: 'UNAVAILABLE', detail: null, model: null, provider: null },
        chroma: { status: 'READY', detail: null, model: null, provider: null },
        embedding_provider: { status: 'READY', detail: null, model: null, provider: null },
      },
    })
    renderWithProviders(<GraphPage />, {
      route: '/repositories/repo-1/graph',
      path: '/repositories/:repositoryId/graph',
    })

    expect(await screen.findByText(/Knowledge graph unavailable/)).toBeInTheDocument()
    await waitFor(() => expect(mockedGraph.getRepositoryGraph).not.toHaveBeenCalled())
  })
})
