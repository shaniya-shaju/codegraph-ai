import { useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router-dom'
import { DependencyBanner } from './DependencyBanner'
import { RepositorySidebarNav } from './RepositorySidebarNav'
import { queryClient } from '../../app/queryClient'

/** The main application layout — see Prompt 11 "Main Application
 * Layout". Sidebar collapses on smaller screens (a toggle button, not a
 * media-query-only collapse, so it also works at tablet width). */
export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800">
        <div className="flex items-center justify-between px-4 py-3 md:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="rounded p-1.5 text-slate-400 hover:bg-slate-800 md:hidden"
              aria-label="Toggle repository navigation"
              aria-expanded={sidebarOpen}
              onClick={() => setSidebarOpen((v) => !v)}
            >
              ☰
            </button>
            <Link to="/" className="text-base font-semibold tracking-tight text-white">
              CodeGraph AI
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <DependencyBanner />
            <button type="button" onClick={() => { sessionStorage.removeItem('codegraph_access_token'); sessionStorage.removeItem('codegraph_user'); queryClient.clear(); navigate('/login', { replace: true }) }} className="rounded-lg border border-slate-700 px-3 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800">Sign out</button>
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-[1600px]">
        <aside
          className={`w-60 shrink-0 border-r border-slate-800 py-4 md:block ${
            sidebarOpen ? 'block' : 'hidden'
          }`}
        >
          <RepositorySidebarNav />
        </aside>
        <main className="min-w-0 flex-1 overflow-x-hidden px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
