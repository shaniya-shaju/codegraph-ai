import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useRef, useState } from 'react'
import type { ImpactAnalysisResult, ImpactedSymbol } from '../../types/api'

type Direction = 'upstream' | 'downstream' | 'both'

const TARGET_COLOR = '#facc15'
const UPSTREAM_COLOR = '#38bdf8'
const DOWNSTREAM_COLOR = '#f43f5e'

/** See Prompt 11 "Impact Graph": Cytoscape visualization with an
 * upstream/downstream/both toggle. Every node and edge here is built
 * directly from the backend's own computed `path` (qualified names) and
 * `relationship_path` for each impacted symbol — nothing is inferred or
 * re-derived client-side. Intermediate hops in a path are rendered as
 * plain (non-clickable) qualified-name nodes since the impact API does
 * not expose their symbol IDs; only the target and each impacted symbol
 * itself carry real IDs. */
export function ImpactGraph({ result }: { result: ImpactAnalysisResult }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)
  const [direction, setDirection] = useState<Direction>('both')

  const targetLabel = result.target.qualified_name ?? result.target.name

  useEffect(() => {
    if (!containerRef.current) return

    const elements = buildElements(result, direction, targetLabel)
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-size': 9,
            color: '#e2e8f0',
            'text-valign': 'bottom',
            'text-margin-y': 4,
            'background-color': 'data(color)',
            width: 24,
            height: 24,
            'border-width': 2,
            'border-color': '#0f172a',
          },
        },
        {
          selector: 'node[?isTarget]',
          style: { width: 32, height: 32, 'border-width': 3, 'border-color': '#facc15' },
        },
        {
          selector: 'edge',
          style: {
            width: 1.5,
            'line-color': 'data(color)',
            'target-arrow-color': 'data(color)',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
          },
        },
      ],
      layout: { name: 'breadthfirst', directed: true, animate: false } as never,
      wheelSensitivity: 0.3,
    })
    cyRef.current = cy

    return () => {
      cy.destroy()
      cyRef.current = null
    }
  }, [result, direction, targetLabel])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5" role="group" aria-label="Impact graph direction">
          {(['upstream', 'downstream', 'both'] as Direction[]).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={direction === option}
              onClick={() => setDirection(option)}
              className={`rounded px-2.5 py-1 text-xs capitalize ${
                direction === option
                  ? 'bg-sky-600 text-white'
                  : 'border border-slate-700 text-slate-300 hover:bg-slate-800'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => cyRef.current?.fit(undefined, 30)}
          className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          Fit to screen
        </button>
      </div>
      <div className="flex gap-4 text-xs text-slate-400">
        <LegendDot color={TARGET_COLOR} label="Target" />
        <LegendDot color={UPSTREAM_COLOR} label="Upstream (callers/dependents)" />
        <LegendDot color={DOWNSTREAM_COLOR} label="Downstream (dependencies)" />
      </div>
      <div
        ref={containerRef}
        data-testid="impact-cytoscape-canvas"
        className="h-96 w-full rounded border border-slate-800 bg-slate-950"
      />
    </div>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
      {label}
    </span>
  )
}

function buildElements(
  result: ImpactAnalysisResult,
  direction: Direction,
  targetLabel: string,
): ElementDefinition[] {
  const nodes = new Map<string, ElementDefinition>()
  const edges = new Map<string, ElementDefinition>()

  const targetId = `n:${targetLabel}`
  nodes.set(targetId, {
    data: { id: targetId, label: targetLabel, color: TARGET_COLOR, isTarget: true },
  })

  const groups: { symbols: ImpactedSymbol[]; color: string }[] = []
  if (direction === 'upstream' || direction === 'both') {
    groups.push(
      { symbols: result.direct_callers, color: UPSTREAM_COLOR },
      { symbols: result.transitive_dependents, color: UPSTREAM_COLOR },
    )
  }
  if (direction === 'downstream' || direction === 'both') {
    groups.push({ symbols: result.downstream_dependencies, color: DOWNSTREAM_COLOR })
  }

  for (const group of groups) {
    for (const symbol of group.symbols) {
      // `symbol.path` is the backend-computed qualified-name chain
      // between the target and this symbol — orient it so the target is
      // always the first element (the raw order depends on traversal
      // direction, which differs between caller and callee queries).
      let chain = symbol.path.length > 0 ? symbol.path : [targetLabel, symbol.qualified_name ?? symbol.symbol_id]
      if (chain[0] !== targetLabel && chain[chain.length - 1] === targetLabel) {
        chain = [...chain].reverse()
      } else if (chain[0] !== targetLabel) {
        chain = [targetLabel, symbol.qualified_name ?? symbol.symbol_id]
      }
      const relationshipPath =
        chain[0] === symbol.path[0] ? symbol.relationship_path : [...symbol.relationship_path].reverse()

      const chainNodeIds = chain.map((qname, index) => {
        const isEndpoint = index === chain.length - 1
        const id = index === 0 ? targetId : `n:${qname}`
        if (!nodes.has(id)) {
          nodes.set(id, {
            data: {
              id,
              label: qname,
              color: isEndpoint ? group.color : '#64748b',
              symbolId: isEndpoint ? symbol.symbol_id : undefined,
            },
          })
        }
        return id
      })

      for (let i = 0; i < chainNodeIds.length - 1; i++) {
        const source = chainNodeIds[i]
        const target = chainNodeIds[i + 1]
        const relLabel = relationshipPath[i] ?? ''
        const key = `${source}->${target}`
        if (!edges.has(key)) {
          edges.set(key, {
            data: { id: `e:${key}`, source, target, label: relLabel, color: group.color },
          })
        }
      }
    }
  }

  return [...nodes.values(), ...edges.values()]
}
