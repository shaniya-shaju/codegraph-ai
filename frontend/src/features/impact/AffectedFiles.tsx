import type { ImpactedFile } from '../../types/api'

/** See Prompt 11 "Affected Files". */
export function AffectedFiles({ files }: { files: ImpactedFile[] }) {
  if (files.length === 0) {
    return <p className="text-xs text-slate-500">No other files are affected by this change.</p>
  }

  return (
    <ul className="space-y-1.5">
      {files.map((file) => (
        <li
          key={file.file_path}
          className="flex items-center justify-between gap-3 rounded border border-slate-800 bg-slate-900 px-3 py-2 text-sm"
        >
          <span className="truncate font-mono text-slate-200">{file.file_path}</span>
          <span className="shrink-0 text-xs text-slate-500">
            {file.affected_symbol_count} symbol{file.affected_symbol_count === 1 ? '' : 's'} ·
            distance {file.minimum_distance}
          </span>
        </li>
      ))}
    </ul>
  )
}
