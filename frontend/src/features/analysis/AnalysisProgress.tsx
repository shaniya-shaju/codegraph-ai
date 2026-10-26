import type { AnalysisState } from '../../types/api'
import { titleCase } from '../../utils/format'

const STAGE_LABELS: Record<string, string> = {
  IMPORT: 'Importing repository',
  SCAN: 'Scanning files',
  PARSE: 'Parsing source code',
  BUILD_GRAPH: 'Building knowledge graph',
  BUILD_VECTOR_INDEX: 'Generating embeddings',
  FINALIZE: 'Finalizing',
  DONE: 'Done',
}

/** See Prompt 11 "Analysis Progress": current stage, progress bar,
 * percentage, files processed / total. Never invents stage history the
 * API didn't supply. */
export function AnalysisProgress({ state }: { state: AnalysisState }) {
  const stageLabel = STAGE_LABELS[state.current_stage] ?? titleCase(state.current_stage)
  const percentage = Math.round(state.progress_percentage)

  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-4" role="status">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-slate-100">{stageLabel}</span>
        <span className="text-slate-400">{percentage}%</span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-sky-500 transition-[width]"
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={percentage}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {state.files_total != null ? (
        <p className="mt-2 text-xs text-slate-400">
          {state.files_processed ?? 0} / {state.files_total} files
        </p>
      ) : null}
    </div>
  )
}
