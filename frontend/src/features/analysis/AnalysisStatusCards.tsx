import type { AnalysisState } from '../../types/api'
import { SubsystemStatusBadge } from '../../components/common/StatusBadge'
import { formatDuration, formatNumber } from '../../utils/format'

/** See Prompt 11 "Repository Overview Page": status cards for
 * Parser/Graph/Vector Index, and "Repository PARTIAL": "show which
 * subsystem failed." */
export function AnalysisStatusCards({ state }: { state: AnalysisState }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <StatusCard
        title="Parser"
        status={state.parser_status}
        stat={`${formatNumber(state.files_processed)} / ${formatNumber(state.files_total)} files`}
        duration={state.parse_duration_ms}
      />
      <StatusCard
        title="Graph"
        status={state.graph_status}
        stat={`${formatNumber(state.graph_node_count)} nodes, ${formatNumber(
          state.graph_relationship_count,
        )} rels`}
        duration={state.graph_build_duration_ms}
        current={state.graph_current}
      />
      <StatusCard
        title="Vector Index"
        status={state.vector_status}
        stat={`${formatNumber(state.vector_chunk_count)} chunks`}
        duration={state.vector_index_duration_ms}
        current={state.vector_current}
      />
    </div>
  )
}

function StatusCard({
  title,
  status,
  stat,
  duration,
  current,
}: {
  title: string
  status: string
  stat: string
  duration: number | null
  current?: boolean
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-200">{title}</span>
        <SubsystemStatusBadge status={status} />
      </div>
      <p className="mt-1 text-xs text-slate-400">{stat}</p>
      <p className="text-xs text-slate-500">Duration: {formatDuration(duration)}</p>
      {current === false ? (
        <p className="mt-1 text-xs text-amber-400">Stale — content changed since last analysis</p>
      ) : null}
    </div>
  )
}
