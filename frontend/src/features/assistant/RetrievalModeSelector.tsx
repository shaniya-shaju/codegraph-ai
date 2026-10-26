import type { ReadinessResponse } from '../../types/api'
import type { RetrievalMode } from '../../types/api'

const MODES: { value: RetrievalMode; label: string; description: string }[] = [
  {
    value: 'hybrid',
    label: 'Hybrid',
    description: 'Combines semantic search and structural graph evidence.',
  },
  { value: 'vector', label: 'Vector', description: 'Uses semantic code retrieval only.' },
  {
    value: 'graph',
    label: 'Graph',
    description: 'Uses deterministic structural relationships only.',
  },
]

/** See Prompt 11 "Retrieval Mode Selector": Hybrid/Vector/Graph, default
 * Hybrid, tooltip explanations, Graph disabled (with reason) when the
 * knowledge graph is unavailable. */
export function RetrievalModeSelector({
  value,
  onChange,
  readiness,
}: {
  value: RetrievalMode
  onChange: (mode: RetrievalMode) => void
  readiness?: ReadinessResponse
}) {
  const graphUnavailable = readiness?.dependencies.neo4j?.status === 'UNAVAILABLE'

  return (
    <div className="flex items-center gap-1 rounded bg-slate-800 p-1 text-xs" role="radiogroup" aria-label="Retrieval mode">
      {MODES.map((mode) => {
        const disabled = mode.value === 'graph' && graphUnavailable
        return (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={value === mode.value}
            disabled={disabled}
            title={disabled ? 'Knowledge graph unavailable' : mode.description}
            onClick={() => onChange(mode.value)}
            className={`rounded px-2 py-1 ${
              value === mode.value ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
            } ${disabled ? 'cursor-not-allowed opacity-40' : ''}`}
          >
            {mode.label}
          </button>
        )
      })}
    </div>
  )
}
