import { Outlet, createRootRoute, useRouterState } from '@tanstack/react-router'
import { BlockedScreen, PlatformOwnerScreen } from '@/features/auth/StatusScreens'
import { LoginScreen } from '@/features/auth/LoginScreen'
import { MfaScreen } from '@/features/auth/MfaScreen'
import { Spinner } from '@/components/ui/spinner'
import { useSession } from '@/session/session'

export const Route = createRootRoute({ component: Root })

// The gate. What is on screen is decided by how far through signing in the
// session is, not by the URL -- so a signed-out visitor to /clients/abc sees the
// login form, and lands on /clients/abc once they are through, with no redirect
// to lose their place.
function Root() {
  const { state } = useSession()
  const path = useRouterState({ select: (s) => s.location.pathname })

  // An invitation is opened by someone who is not signed in yet.
  if (path.startsWith('/invite/')) return <Outlet />

  switch (state.kind) {
    case 'loading':
      return <Spinner label="Checking your session…" className="min-h-svh" />
    case 'anonymous':
      return <LoginScreen />
    case 'mfa':
      return <MfaScreen step={state.step} />
    case 'blocked':
      return <BlockedScreen detail={state.detail} />
    case 'platform':
      return <PlatformOwnerScreen />
    case 'ready':
      return <Outlet />
  }
}
