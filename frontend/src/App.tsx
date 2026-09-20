import { useEffect } from 'react'
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from 'react-router-dom'
import { SessionProvider, useSession } from './auth/session'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
import Mfa from './pages/Mfa'
import Clients from './pages/Clients'
import ClientPage from './pages/ClientPage'
import Help from './pages/Help'
import Team from './pages/team/Team'
import MyWork from './pages/MyWork'
import AcceptInvite from './pages/AcceptInvite'
import FirmSettings from './pages/FirmSettings'
import AuditLog from './pages/AuditLog'

// The platform owner belongs to no firm, so this app has nothing to show them:
// every screen here is one firm's work. Their panel is the Django admin, which
// lives outside this app's router, so this is a full page navigation.
function ToPlatformAdmin() {
  useEffect(() => {
    window.location.replace('/admin/')
  }, [])
  return <Spinner label="Opening the platform admin…" />
}

function Blocked({ detail }: { detail: string }) {
  const { signOut } = useSession()
  return (
    <div className="auth">
      <div className="auth-card">
        <div className="brand">
          <span className="brand-mark">₹</span>
          <span>AutoCA</span>
        </div>
        <h1>No access right now</h1>
        <p className="sub">{detail}</p>
        <p className="sub">Your firm's owner or administrator can switch your access back on. If the whole firm is deactivated, contact AutoCA.</p>
        <button type="button" className="btn btn-primary" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
    </div>
  )
}

function Gate() {
  const { state } = useSession()
  const location = useLocation()
  if (state.kind === 'loading') return <Spinner label="Checking your session…" />
  if (state.kind === 'anonymous') return <Login />
  if (state.kind === 'mfa') return <Mfa step={state.step} />
  if (state.kind === 'blocked') return <Blocked detail={state.detail} />
  if (!state.me.firm) return <ToPlatformAdmin />
  if (location.pathname === '/') return <Navigate to="/clients" replace />
  return <Layout />
}

const router = createBrowserRouter(
  [
    // Outside the gate: whoever opens an invite link is not signed in yet.
    { path: '/invite/:token', element: <AcceptInvite /> },
    {
      path: '/',
      element: <Gate />,
      children: [
        { index: true, element: <Navigate to="/clients" replace /> },
        { path: 'clients', element: <Clients /> },
        { path: 'clients/:clientId/*', element: <ClientPage /> },
        { path: 'help', element: <Help /> },
        { path: 'team/*', element: <Team /> },
        { path: 'my-work', element: <MyWork /> },
        { path: 'firm', element: <FirmSettings /> },
        { path: 'audit', element: <AuditLog /> },
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
