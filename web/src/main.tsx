import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import { ApiError } from '@/api/errors'
import { PreferencesProvider } from '@/lib/preferences'
import { SessionProvider } from '@/session/session'
import { routeTree } from './routeTree.gen'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // A refusal is an answer, not a glitch: asking again gets the same one.
      retry: (count, error) => !(error instanceof ApiError) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
})

const router = createRouter({ routeTree, defaultPreload: 'intent', scrollRestoration: true })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PreferencesProvider>
        <SessionProvider>
          <RouterProvider router={router} />
          <Toaster position="bottom-right" duration={6000} richColors closeButton />
        </SessionProvider>
      </PreferencesProvider>
    </QueryClientProvider>
  </StrictMode>,
)
