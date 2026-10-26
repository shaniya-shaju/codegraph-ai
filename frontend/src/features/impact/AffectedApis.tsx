import type { ImpactedEndpoint } from '../../types/api'

/** See Prompt 11 "Affected APIs". */
export function AffectedApis({ endpoints }: { endpoints: ImpactedEndpoint[] }) {
  if (endpoints.length === 0) {
    return <p className="text-xs text-slate-500">No API endpoints are affected by this change.</p>
  }

  return (
    <ul className="space-y-2">
      {endpoints.map((endpoint) => (
        <li
          key={endpoint.endpoint_id}
          className="rounded border border-slate-800 bg-slate-900 p-3 text-sm"
        >
          <div className="flex items-center gap-2">
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-mono uppercase text-sky-300">
              {endpoint.http_method}
            </span>
            <span className="font-mono text-slate-100">{endpoint.route_path}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Handler: {endpoint.handler_qualified_name ?? endpoint.handler_symbol_id} · distance{' '}
            {endpoint.distance_from_target}
          </p>
          <p className="mt-1 text-xs text-slate-400">{endpoint.impact_reason}</p>
        </li>
      ))}
    </ul>
  )
}
