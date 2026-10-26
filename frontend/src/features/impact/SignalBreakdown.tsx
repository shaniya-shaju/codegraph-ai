import type { ImpactSignal } from '../../types/api'

const SIGNAL_LABEL: Record<string, string> = {
  DIRECT_CALLER_COUNT: 'Direct callers',
  TRANSITIVE_DEPENDENT_COUNT: 'Transitive dependents',
  AFFECTED_FILE_COUNT: 'Affected files',
  AFFECTED_MODULE_COUNT: 'Affected modules',
  PUBLIC_API_EXPOSURE: 'Public API exposure',
  CROSS_MODULE_DEPENDENCY: 'Cross-module dependency',
  EXTERNAL_DEPENDENCY_INTERACTION: 'External dependency interaction',
  INHERITANCE_IMPACT: 'Inheritance impact',
  GRAPH_CENTRALITY: 'Graph centrality',
  RELATED_TEST_SIGNAL: 'Related test signal',
}

/** See Prompt 11 "Risk Signal Breakdown": render the backend's raw /
 * normalized / contribution / explanation values exactly as returned —
 * never recompute or re-derive the risk score in JavaScript. */
export function SignalBreakdown({ signals }: { signals: ImpactSignal[] }) {
  if (signals.length === 0) {
    return <p className="text-xs text-slate-500">No risk signals were computed.</p>
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-800">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-3 py-2">Signal</th>
            <th className="px-3 py-2">Raw</th>
            <th className="px-3 py-2">Normalized</th>
            <th className="px-3 py-2">Contribution</th>
            <th className="px-3 py-2">Explanation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {signals.map((signal) => (
            <tr key={signal.signal_type}>
              <td className="px-3 py-2 font-medium text-slate-200">
                {SIGNAL_LABEL[signal.signal_type] ?? signal.signal_type}
              </td>
              <td className="px-3 py-2 text-slate-300">{signal.raw_value}</td>
              <td className="px-3 py-2 text-slate-300">{signal.normalized_value.toFixed(2)}</td>
              <td className="px-3 py-2 text-slate-300">{signal.contribution.toFixed(2)}</td>
              <td className="px-3 py-2 text-slate-400">{signal.explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
