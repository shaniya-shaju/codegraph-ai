import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { SourceViewerProvider } from '../features/source/SourceViewerContext'

/** Shared test rendering helper — a fresh, retry-disabled QueryClient
 * per render (so failed queries surface immediately in tests instead of
 * retrying), wrapped in a MemoryRouter so route params/navigation work
 * the same way they do in the app, and `SourceViewerProvider` so any
 * citation/node/impact-row "view source" action works exactly as it
 * does mounted under the real `app/App.tsx`. */
export function renderWithProviders(
  ui: ReactElement,
  { route = '/', path = '/' }: { route?: string; path?: string } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <SourceViewerProvider>
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        </SourceViewerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
