import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { searchSymbols } from '../../api/graph'
import type { SymbolSearchResult } from '../../types/api'

/** A reusable symbol-search component — see Prompt 11 "Symbol Search":
 * shows type/qualified name/file/line per result, and never silently
 * picks the first match when a name is ambiguous (multiple results are
 * simply all shown). */
export function SymbolSearch({
  repositoryId,
  onSelect,
  placeholder = 'Search symbols…',
}: {
  repositoryId: string
  onSelect: (result: SymbolSearchResult) => void
  placeholder?: string
}) {
  const [query, setQuery] = useState('')

  const searchQuery = useQuery({
    queryKey: ['symbol-search', repositoryId, query],
    queryFn: ({ signal }) => searchSymbols(repositoryId, query, { limit: 15 }, signal),
    enabled: query.trim().length > 1,
  })

  const results = searchQuery.data ?? []

  return (
    <div className="relative">
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={placeholder}
        aria-label="Search symbols"
        className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500"
      />
      {query.trim().length > 1 ? (
        <div className="absolute z-20 mt-1 max-h-80 w-full overflow-y-auto rounded border border-slate-800 bg-slate-900 shadow-lg">
          {searchQuery.isPending ? (
            <p className="px-3 py-2 text-xs text-slate-500">Searching…</p>
          ) : null}
          {searchQuery.isSuccess && results.length === 0 ? (
            <p className="px-3 py-2 text-xs text-slate-500">No matching symbols.</p>
          ) : null}
          {results.length > 0 ? (
            <p className="px-3 pt-2 text-xs text-slate-500">
              {results.length} match{results.length === 1 ? '' : 'es'}
            </p>
          ) : null}
          <ul>
            {results.map((result) => (
              <li key={result.symbol_id}>
                <button
                  type="button"
                  onClick={() => onSelect(result)}
                  className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm hover:bg-slate-800"
                >
                  <span className="flex items-center gap-2">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                      {result.symbol_type}
                    </span>
                    <span className="font-mono text-slate-100">
                      {result.qualified_name ?? result.name}
                    </span>
                  </span>
                  {result.file_path ? (
                    <span className="text-xs text-slate-500">
                      {result.file_path}
                      {result.start_line ? `:${result.start_line}` : ''}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
