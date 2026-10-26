import type { ImpactAnalysisResult } from '../../types/api'
import { formatNumber } from '../../utils/format'

/** See Prompt 11 "Impact Statistics" / "Impact Summary Cards": counts
 * only, taken directly off the backend result — nothing computed here. */
export function ImpactStatsCards({ result }: { result: ImpactAnalysisResult }) {
  const cards: { label: string; value: number }[] = [
    { label: 'Total impacted symbols', value: result.total_impacted_symbols },
    { label: 'Direct callers', value: result.direct_callers.length },
    { label: 'Transitive dependents', value: result.transitive_dependents.length },
    { label: 'Downstream dependencies', value: result.downstream_dependencies.length },
    { label: 'Affected files', value: result.affected_files.length },
    { label: 'Affected APIs', value: result.affected_endpoints.length },
    { label: 'Traversal depth', value: result.traversal_depth },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded border border-slate-800 bg-slate-900 p-3">
          <p className="text-xl font-semibold text-slate-100">{formatNumber(card.value)}</p>
          <p className="text-xs text-slate-500">{card.label}</p>
        </div>
      ))}
    </div>
  )
}
