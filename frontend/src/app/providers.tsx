import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { SourceViewerProvider } from '../features/source/SourceViewerContext'
import { queryClient } from './queryClient'

/** All app-wide providers in one place — see Prompt 11's own "one place"
 * design philosophy, mirrored from the backend. `SourceViewerProvider`
 * is mounted once here so any feature can open the same source drawer
 * without prop-drilling. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SourceViewerProvider>{children}</SourceViewerProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
