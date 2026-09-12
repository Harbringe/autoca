import { NavLink, Outlet } from 'react-router-dom'
import { useSession } from '../auth/session'

export default function Layout() {
  const { me, signOut } = useSession()
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">₹</span>
          <span>AutoCA</span>
        </div>
        <nav>
          <NavLink to="/clients" end>
            Clients
          </NavLink>
          <NavLink to="/help">How it works</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="who">
            <div className="who-firm">{me?.firm?.name}</div>
            <div className="who-user">{me?.email}</div>
            <div className="who-role">{me?.role_display}</div>
          </div>
          <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
