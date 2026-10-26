import { useQuery } from '@tanstack/react-query'
import { NavLink, useParams } from 'react-router-dom'
import { getAnalysisState } from '../../api/analysis'
import { getRepository } from '../../api/repositories'

const NAV_ITEMS = [
  { to: '', label: 'Overview', end: true, icon: '▤' },
  { to: 'assistant', label: 'Assistant', end: false, icon: '◆' },
  { to: 'graph', label: 'Graph', end: false, icon: '◇' },
  { to: 'impact', label: 'Impact', end: false, icon: '▲' },
]

export function RepositorySidebarNav() {
  const { repositoryId } = useParams<{ repositoryId: string }>()

  const repositoryQuery = useQuery({
    queryKey: ['repository', repositoryId],
    queryFn: ({ signal }) => getRepository(repositoryId as string, signal),
    enabled: Boolean(repositoryId),
  })
  useQuery({
    queryKey: ['analysis', repositoryId],
    queryFn: ({ signal }) => getAnalysisState(repositoryId as string, signal),
    enabled: Boolean(repositoryId),
  })

  if (!repositoryId) {
    return (
      <p className="px-3 text-xs text-slate-500 dark:text-slate-400">
        Select a repository from the dashboard.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <div className="px-3">
        {/* Repository Name: Dark slate in light mode, crisp white in dark mode */}
        <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100" title={repositoryQuery.data?.name}>
          {repositoryQuery.data?.name ?? 'Loading…'}
        </p>
      </div>
      <nav className="flex flex-col gap-1 px-1" aria-label="Repository sections">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.label}
            to={`/repositories/${repositoryId}/${item.to}`}
            end={item.end}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded px-2.5 py-1.5 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-white font-semibold'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-200'
              }`
            }
          >
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}