import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { allPages, api, V1 } from '../api/client'
import type { Client } from '../api/types'
import { Badge, Button, Empty, ErrorNote, formatDateTime, Spinner, useAsync } from '../components/ui'

interface AuditRow {
  id: string
  at: string
  who: string
  email: string | null
  action: string
  client_id: string | null
  succeeded: boolean
  status_code: number
  ip_address: string | null
}

interface Page {
  results: AuditRow[]
  next: string | null
}

export default function AuditLog() {
  const [person, setPerson] = useState('')
  const [client, setClient] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [failedOnly, setFailedOnly] = useState(false)
  const [rows, setRows] = useState<AuditRow[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  const people = useAsync(() => api.get<{ results: { id: string; name: string }[] }>(`${V1}/team/members/`), [])
  const clients = useAsync(() => allPages<Client>(`${V1}/clients/`), [])

  useEffect(() => {
    const params = new URLSearchParams()
    if (person) params.set('user', person)
    if (client) params.set('client', client)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    if (failedOnly) params.set('failed', 'true')
    let live = true
    setLoading(true)
    setError(null)
    api.get<Page>(`${V1}/audit/?${params}`).then(
      (page) => {
        if (!live) return
        setRows(page.results)
        setNext(page.next)
        setLoading(false)
      },
      (err) => live && (setError(err), setLoading(false)),
    )
    return () => {
      live = false
    }
  }, [person, client, from, to, failedOnly])

  async function more() {
    if (!next) return
    try {
      const page = await api.get<Page>(next.replace(/^https?:\/\/[^/]+/, ''))
      setRows((current) => [...current, ...page.results])
      setNext(page.next)
    } catch (err) {
      setError(err)
    }
  }

  const clientName = (id: string | null) => clients.data?.find((c) => c.id === id)?.name
  const filtered = person || client || from || to || failedOnly

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <p className="sub">Every change anyone in the firm made, newest first. Viewing pages isn't recorded; changes are.</p>
        </div>
      </div>

      <div className="panel">
        <div className="panel-body row">
          <select value={person} onChange={(e) => setPerson(e.target.value)} aria-label="Person">
            <option value="">Everyone</option>
            {people.data?.results.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select value={client} onChange={(e) => setClient(e.target.value)} aria-label="Client">
            <option value="">All clients</option>
            {clients.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <label className="row" style={{ gap: 6 }}>
            From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="row" style={{ gap: 6 }}>
            To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> Refused or failed only
          </label>
          {filtered && (
            <Button
              kind="ghost"
              onClick={() => {
                setPerson('')
                setClient('')
                setFrom('')
                setTo('')
                setFailedOnly(false)
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      </div>

      <ErrorNote error={error} />
      <div className="panel">
        {loading ? (
          <Spinner />
        ) : !rows.length ? (
          <Empty title={filtered ? 'Nothing matches these filters' : 'Nothing recorded yet'} />
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>What</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(row.at)}</td>
                    <td>
                      <strong>{row.who}</strong>
                      {row.email && row.email !== row.who && <div className="sub">{row.email}</div>}
                    </td>
                    <td>
                      {row.action}
                      {row.client_id && clientName(row.client_id) && (
                        <div className="sub">
                          <Link to={`/clients/${row.client_id}`}>Open {clientName(row.client_id)}</Link>
                        </div>
                      )}
                    </td>
                    <td>
                      {row.succeeded ? (
                        <Badge tone="good">Done</Badge>
                      ) : (
                        <Badge tone={row.status_code >= 500 ? 'bad' : 'warn'}>
                          {row.status_code === 403 ? 'Not allowed' : row.status_code >= 500 ? 'Failed' : 'Refused'}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {next && (
          <div className="panel-body row end">
            <Button onClick={() => void more()}>Load older</Button>
          </div>
        )}
      </div>
    </>
  )
}
