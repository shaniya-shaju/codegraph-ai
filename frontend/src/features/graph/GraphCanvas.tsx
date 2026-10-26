import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { GraphSubgraph } from '../../types/api'
import { cytoscapeStylesheet, EDGE_COLOR_BY_TYPE, NODE_COLOR_BY_LABEL, NODE_SHAPE_BY_LABEL } from './graphStyle'

function toElements(subgraph: GraphSubgraph, targetNodeId?: string): ElementDefinition[] {
  const nodes: ElementDefinition[] = subgraph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.name,
      shape: NODE_SHAPE_BY_LABEL[node.label] ?? 'ellipse',
      color: NODE_COLOR_BY_LABEL[node.label] ?? '#38bdf8',
      isTarget: node.id === targetNodeId,
      nodeLabel: node.label,
    },
  }))
  const edges: ElementDefinition[] = subgraph.edges
    // Cytoscape requires both endpoints to exist as nodes in the same
    // element set — the backend already guarantees this for a subgraph,
    // but guard defensively rather than letting cytoscape throw.
    .filter(
      (edge) =>
        subgraph.nodes.some((n) => n.id === edge.source_id) &&
        subgraph.nodes.some((n) => n.id === edge.target_id),
    )
    .map((edge) => ({
      data: {
        id: edge.id,
        source: edge.source_id,
        target: edge.target_id,
        label: edge.relationship_type,
        color: EDGE_COLOR_BY_TYPE[edge.relationship_type] ?? '#64748b',
      },
    }))
  return [...nodes, ...edges]
}

/** A thin, testable Cytoscape wrapper — see Prompt 11 "Graph Page" /
 * "Tests": "Cytoscape itself may be mocked at component-boundary level
 * where appropriate." Owns only rendering + selection; never computes
 * graph relationships itself (those always come from the backend). */
export function GraphCanvas({
  subgraph,
  targetNodeId,
  onSelectNode,
  fitSignal,
}: {
  subgraph: GraphSubgraph
  targetNodeId?: string
  onSelectNode: (nodeId: string) => void
  fitSignal?: number
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(subgraph, targetNodeId),
      style: cytoscapeStylesheet(),
      layout: { name: 'cose', animate: false } as never,
      wheelSensitivity: 0.3,
    })
    cy.on('tap', 'node', (event) => {
      onSelectNode(event.target.id())
    })
    cyRef.current = cy

    return () => {
      cy.destroy()
      cyRef.current = null
    }
    // Re-created whenever the subgraph itself changes (new data) — a
    // stable identity isn't preserved across queries here on purpose,
    // since node/edge sets can change shape entirely between requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subgraph])

  useEffect(() => {
    cyRef.current?.fit(undefined, 30)
  }, [fitSignal, subgraph])

  return (
    <div
      ref={containerRef}
      data-testid="cytoscape-canvas"
      className="h-full w-full rounded border border-slate-800 bg-slate-950"
    />
  )
}
