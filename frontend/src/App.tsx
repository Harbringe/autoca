import { createBrowserRouter, Navigate, RouterProvider, useLocation } from 'react-router-dom'
import { SessionProvider, useSession } from './auth/session'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
import Mfa from './pages/Mfa'
import Clients from './pages/Clients'
import ClientPage from './pages/ClientPage'
import Help from './pages/Help'

function Gate() {
  const { state } = useSession()
  const location = useLocation()
  if (state.kind === 'loading') return <Spinner label="Checking your session…" />
  if (state.kind === 'anonymous') return <Login />
  if (state.kind === 'mfa') return <Mfa step={state.step} />
  if (location.pathname === '/') return <Navigate to="/clients" replace />
  return <Layout />
}

const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <Gate />,
      children: [
        { index: true, element: <Navigate to="/clients" replace /> },
        { path: 'clients', element: <Clients /> },
        { path: 'clients/:clientId/*', element: <ClientPage /> },
        { path: 'help', element: <Help /> },
        { path: '*', element: <Navigate to="/clients" replace /> },
      ],
    },
  ],
  { basename: '/app' },
)

export default function App() {
  return (
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>
  )
}
