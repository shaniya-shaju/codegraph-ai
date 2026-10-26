import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getRepositoryGraph, getSymbol, getSymbolCallees, getSymbolCallers, getSymbolDependencies } from '../api/graph'
import { ErrorState } from '../components/common/ErrorState'
import { Skeleton } from '../components/common/Skeleton'
import { GraphCanvas } from '../features/graph/GraphCanvas'
import { GraphControls } from '../features/graph/GraphControls'
import { NodeDetailPanel } from '../features/graph/NodeDetailPanel'
import { SymbolSearch } from '../features/symbols/SymbolSearch'
import { useDependencyStatus } from '../hooks/useDependencyStatus'
import type { NodeLabel, RelationshipType, SymbolSearchResult } from '../types/api'

const ALL_LABELS: NodeLabel[] = [
  'File',
  'Module',
  'Class',
  'Function',
  'Method',
  'APIEndpoint',
  'ExternalDependency',
  'Parameter',
  'Directory',
  'Repository',
]
const ALL_RELATIONSHIPS: RelationshipType[] = [
  'CALLS',
  'IMPORTS',
  'EXTENDS',
  'DEFINES',
  'HANDLED_BY',
  'DEPENDS_ON',
  'CONTAINS',
  'HAS_PARAMETER',
  'REFERENCES',
]

type GraphView =
  | { kind: 'neighborhood'; label: string; rootSymbolId?: string }
  | { kind: 'callers'; label: string; symbolId: string }
  | { kind: 'callees'; label: string; symbolId: string }
  | { kind: 'dependencies'; label: string; symbolId: string }

/** `/repositories/:repositoryId/graph` — see Prompt 11 "Graph Page".
 * Renders a bounded default subgraph, never an unbounded one; caller /
 * callee / dependency exploration and the impact/assistant hand-offs all
 * reuse backend-computed relationships (nothing here derives graph
 * structure client-side). */
export function GraphPage() {
  const { repositoryId } = useParams<{ repositoryId: string }>()
  const { data: readiness } = useDependencyStatus()
  const graphUnavailable = readiness?.dependencies.neo4j?.status === 'UNAVAILABLE'

  const [depth, setDepth] = useState(2)
  const [viewStack, setViewStack] = useState<GraphView[]>([
    { kind: 'neighborhood', label: 'Repository overview' },
  ])
  const [selectedNodeId, setSelectedNodeId] = useState<string | undefined>(undefined)
  const [activeLabels, setActiveLabels] = useState<Set<NodeLabel>>(new Set(ALL_LABELS))
  const [activeRelationships, setActiveRelationships] = useState<Set<RelationshipType>>(
    new Set(ALL_RELATIONSHIPS),
  )
  const [fitSignal, setFitSignal] = useState(0)

  const currentView = viewStack[viewStack.length - 1]

  const graphQuery = useQuery({
    queryKey: ['graph', repositoryId, currentView, depth],
    queryFn: () => {
      if (!repositoryId) throw new Error('missing repositoryId')
      switch (currentView.kind) {
        case 'callers':
          return getSymbolCallers(repositoryId, currentView.symbolId)
        case 'callees':
          return getSymbolCallees(repositoryId, currentView.symbolId)
        case 'dependencies':
          return getSymbolDependencies(repositoryId, currentView.symbolId)
        case 'neighborhood':
        default:
          return getRepositoryGraph(repositoryId, { rootSymbolId: currentView.rootSymbolId, depth })
      }
    },
    // Wait until readiness has actually resolved before firing — otherwise
    // this would race ahead of the degraded-state check below on first
    // render (readiness starts undefined, so `graphUnavailable` would
    // read as false for a moment even when Neo4j is actually down).
    enabled: Boolean(repositoryId) && readiness !== undefined && !graphUnavailable,
  })

  const selectedNodeQuery = useQuery({
    queryKey: ['symbol', repositoryId, selectedNodeId],
    queryFn: () => getSymbol(repositoryId as string, selectedNodeId as string),
    enabled: Boolean(repositoryId && selectedNodeId),
  })

  const filteredSubgraph = useMemo(() => {
    if (!graphQuery.data) return undefined
    const nodes = graphQuery.data.nodes.filter((node) => activeLabels.has(node.label))
    const visibleIds = new Set(nodes.map((n) => n.id))
    const edges = graphQuery.data.edges.filter(
      (edge) =>
        activeRelationships.has(edge.relationship_type) &&
        visibleIds.has(edge.source_id) &&
        visibleIds.has(edge.target_id),
    )
    return { ...graphQuery.data, nodes, edges }
  }, [graphQuery.data, activeLabels, activeRelationships])

  function pushView(view: GraphView) {
    setViewStack((prev) => [...prev, view])
    setSelectedNodeId(undefined)
  }

  function jumpToBreadcrumb(index: number) {
    setViewStack((prev) => prev.slice(0, index + 1))
    setSelectedNodeId(undefined)
  }

  function handleSelectSymbol(result: SymbolSearchResult) {
    setViewStack([
      {
        kind: 'neighborhood',
        label: result.qualified_name ?? result.name,
        rootSymbolId: result.symbol_id,
      },
    ])
    setSelectedNodeId(result.symbol_id)
  }

  function toggleLabel(label: NodeLabel) {
    setActiveLabels((prev) => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  function toggleRelationship(type: RelationshipType) {
    setActiveRelationships((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  function resetFilters() {
    setActiveLabels(new Set(ALL_LABELS))
    setActiveRelationships(new Set(ALL_RELATIONSHIPS))
  }

  const selectedNode = selectedNodeQuery.data

  if (!repositoryId) {
    return <ErrorState error={new Error('Missing repository id.')} />
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-slate-100">Graph Explorer</h1>
        <div className="w-80">
          <SymbolSearch repositoryId={repositoryId} onSelect={handleSelectSymbol} />
        </div>
      </div>

      {viewStack.length > 0 ? (
        <nav aria-label="Graph navigation breadcrumbs" className="flex flex-wrap items-center gap-1 text-xs text-slate-400">
          {viewStack.map((view, index) => (
            <span key={`${view.kind}-${index}`} className="flex items-center gap-1">
              {index > 0 ? <span aria-hidden="true">/</span> : null}
              {index === viewStack.length - 1 ? (
                <span className="text-slate-200">{view.label}</span>
              ) : (
                <button
                  type="button"
                  onClick={() => jumpToBreadcrumb(index)}
                  className="underline-offset-2 hover:underline"
                >
                  {view.label}
                </button>
              )}
            </span>
          ))}
        </nav>
      ) : null}

      {graphUnavailable ? (
        <div
          role="status"
          className="rounded border border-amber-900 bg-amber-950/30 px-4 py-3 text-sm text-amber-300"
        >
          Knowledge graph unavailable. Graph exploration requires Neo4j; it will resume
          automatically once the connection is restored.
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-1 gap-3 overflow-hidden lg:grid-cols-[220px_1fr_300px]">
          <div className="overflow-y-auto">
            <GraphControls
              depth={depth}
              onDepthChange={(value) => setDepth(value)}
              activeLabels={activeLabels}
              onToggleLabel={toggleLabel}
              activeRelationships={activeRelationships}
              onToggleRelationship={toggleRelationship}
              onFit={() => setFitSignal((n) => n + 1)}
              onReset={resetFilters}
            />
          </div>

          <div className="min-h-96 overflow-hidden">
            {graphQuery.isPending ? <Skeleton className="h-full w-full" /> : null}
            {graphQuery.isError ? (
              <ErrorState error={graphQuery.error} onRetry={() => graphQuery.refetch()} />
            ) : null}
            {filteredSubgraph ? (
              <GraphCanvas
                subgraph={filteredSubgraph}
                targetNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                fitSignal={fitSignal}
              />
            ) : null}
            {graphQuery.data?.truncated ? (
              <p className="mt-1 text-xs text-slate-500">
                Showing a bounded subgraph (result limit {graphQuery.data.result_limit}). Narrow
                your search or reduce depth to see a different slice.
              </p>
            ) : null}
          </div>

          <div className="overflow-y-auto">
            {selectedNodeId && selectedNodeQuery.isPending ? <Skeleton className="h-32 w-full" /> : null}
            {selectedNodeQuery.isError ? <ErrorState error={selectedNodeQuery.error} /> : null}
            {selectedNode ? (
              <NodeDetailPanel
                node={selectedNode}
                repositoryId={repositoryId}
                onShowCallers={() =>
                  pushView({
                    kind: 'callers',
                    symbolId: selectedNode.id,
                    label: `Callers of ${selectedNode.qualified_name ?? selectedNode.name}`,
                  })
                }
                onShowCallees={() =>
                  pushView({
                    kind: 'callees',
                    symbolId: selectedNode.id,
                    label: `Callees of ${selectedNode.qualified_name ?? selectedNode.name}`,
                  })
                }
                onShowDependencies={() =>
                  pushView({
                    kind: 'dependencies',
                    symbolId: selectedNode.id,
                    label: `Dependencies of ${selectedNode.qualified_name ?? selectedNode.name}`,
                  })
                }
              />
            ) : (
              <p className="rounded border border-slate-800 bg-slate-900 p-4 text-xs text-slate-500">
                Select a node in the graph, or search for a symbol above, to see its details here.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
