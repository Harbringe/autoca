import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { api, V1 } from '../api/client'
import type { Client } from '../api/types'
import { ErrorNote, Spinner, useAsync } from '../components/ui'
import Statements from './client/Statements'
import ReviewQueue from './client/ReviewQueue'
import Ledger from './client/Ledger'
import Reports from './client/Reports'
import ChartOfAccounts from './client/ChartOfAccounts'
import Vendors from './client/Vendors'
import Rules from './client/Rules'
import StatementRows from './client/StatementRows'

export default function ClientPage() {
  const { clientId = '' } = useParams()
  const { data: client, error, loading } = useAsync(() => api.get<Client>(`${V1}/clients/${clientId}/`), [clientId])

  if (loading) return <Spinner />
  if (error || !client) return <ErrorNote error={error ?? 'Client not found'} />

  // Absolute on purpose: this component renders under a splat route, where a
  // relative link resolves against the current URL and keeps appending.
  const base = `/clients/${client.id}`

  return (
    <>
      <div className="page-head">
        <div>
          <div className="crumbs">
            <Link to="/clients">Clients</Link> / {client.name}
          </div>
          <h1>{client.name}</h1>
        </div>
      </div>
      <nav className="tabs">
        <NavLink to={base} end>
          Statements
        </NavLink>
        <NavLink to={`${base}/review`}>Review queue</NavLink>
        <NavLink to={`${base}/ledger`}>Ledger</NavLink>
        <NavLink to={`${base}/reports`}>Reports</NavLink>
        <NavLink to={`${base}/accounts`}>Chart of accounts</NavLink>
        <NavLink to={`${base}/vendors`}>Vendors</NavLink>
        <NavLink to={`${base}/rules`}>Rules</NavLink>
      </nav>
      <Routes>
        <Route index element={<Statements client={client} />} />
        <Route path="statements/:statementId" element={<StatementRows client={client} />} />
        <Route path="review" element={<ReviewQueue client={client} />} />
        <Route path="ledger" element={<Ledger client={client} />} />
        <Route path="reports" element={<Reports client={client} />} />
        <Route path="accounts" element={<ChartOfAccounts client={client} />} />
        <Route path="vendors" element={<Vendors client={client} />} />
        <Route path="rules" element={<Rules client={client} />} />
      </Routes>
    </>
  )
}
