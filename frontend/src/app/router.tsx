import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from '../components/layout/AppShell'
import { AssistantPage } from '../pages/AssistantPage'
import { AuthPage } from '../pages/AuthPage'
import { DashboardPage } from '../pages/DashboardPage'
import { GraphPage } from '../pages/GraphPage'
import { ImpactPage } from '../pages/ImpactPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { RepositoryPage } from '../pages/RepositoryPage'

function RequireAuth() {
  const location = useLocation()
  if (!sessionStorage.getItem('codegraph_access_token')) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  return <Outlet />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="repositories/:repositoryId" element={<RepositoryPage />} />
          <Route path="repositories/:repositoryId/assistant" element={<AssistantPage />} />
          <Route path="repositories/:repositoryId/graph" element={<GraphPage />} />
          <Route path="repositories/:repositoryId/impact" element={<ImpactPage />} />
          <Route path="repositories/:repositoryId/impact/:symbolId" element={<ImpactPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
