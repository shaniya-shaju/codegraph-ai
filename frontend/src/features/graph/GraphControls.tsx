import type { NodeLabel, RelationshipType } from '../../types/api'

const DEPTH_OPTIONS = [1, 2, 3] as const
const ALL_NODE_LABELS: NodeLabel[] = [
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
const ALL_RELATIONSHIP_TYPES: RelationshipType[] = [
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

/** See Prompt 11 "Graph Controls": search / depth (1-2-3) / node-type
 * filter / relationship-type filter / fit / reset — all bounded, nothing
 * here fetches an unbounded graph. */
export function GraphControls({
  depth,
  onDepthChange,
  activeLabels,
  onToggleLabel,
  activeRelationships,
  onToggleRelationship,
  onFit,
  onReset,
}: {
  depth: number
  onDepthChange: (depth: number) => void
  activeLabels: Set<NodeLabel>
  onToggleLabel: (label: NodeLabel) => void
  activeRelationships: Set<RelationshipType>
  onToggleRelationship: (type: RelationshipType) => void
  onFit: () => void
  onReset: () => void
}) {
  return (
    <div className="space-y-4 rounded border border-slate-800 bg-slate-900 p-3 text-sm">
      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">Depth</p>
        <div className="flex gap-1.5" role="group" aria-label="Traversal depth">
          {DEPTH_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={depth === option}
              onClick={() => onDepthChange(option)}
              className={`rounded px-2.5 py-1 text-xs ${
                depth === option
                  ? 'bg-sky-600 text-white'
                  : 'border border-slate-700 text-slate-300 hover:bg-slate-800'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
          Node types
        </p>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by node type">
          {ALL_NODE_LABELS.map((label) => (
            <FilterChip
              key={label}
              label={label}
              active={activeLabels.has(label)}
              onClick={() => onToggleLabel(label)}
            />
          ))}
        </div>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">
          Relationships
        </p>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by relationship type">
          {ALL_RELATIONSHIP_TYPES.map((type) => (
            <FilterChip
              key={type}
              label={type}
              active={activeRelationships.has(type)}
              onClick={() => onToggleRelationship(type)}
            />
          ))}
        </div>
      </div>

      <div className="flex gap-2 border-t border-slate-800 pt-3">
        <button
          type="button"
          onClick={onFit}
          className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          Fit to screen
        </button>
        <button
          type="button"
          onClick={onReset}
          className="rounded border border-slate-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          Reset filters
        </button>
      </div>
    </div>
  )
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded px-2 py-0.5 text-[11px] ${
        active
          ? 'bg-sky-600 text-white'
          : 'border border-slate-700 text-slate-400 hover:bg-slate-800'
      }`}
    >
      {label}
    </button>
  )
}
