import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { allPages, api, V1 } from '../api/client'
import type { Client } from '../api/types'
import { useSession } from '../auth/session'
import { Button, Empty, ErrorNote, Field, formatDate, Modal, Spinner, useAsync } from '../components/ui'

export default function Clients() {
  const { can } = useSession()
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const { data, error, loading, reload } = useAsync(
    () => allPages<Client>(`${V1}/clients/${search ? `?search=${encodeURIComponent(search)}` : ''}`),
    [search],
  )

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Clients</h1>
          <p className="sub">Every piece of work happens inside one client's books.</p>
        </div>
        <div className="actions">
          <input type="search" placeholder="Search by name" value={search} onChange={(e) => setSearch(e.target.value)} />
          {can('client.create') && (
            <Button kind="primary" onClick={() => setCreating(true)}>
              New client
            </Button>
          )}
        </div>
      </div>

      <ErrorNote error={error} />
      <div className="panel">
        {loading ? (
          <Spinner />
        ) : !data?.length ? (
          <Empty title="No clients yet">Create one, then upload their first bank statement.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Financial year starts</th>
                  <th>Added</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.map((client) => (
                  <tr key={client.id}>
                    <td>
                      <Link to={`/clients/${client.id}`}>
                        <strong>{client.name}</strong>
                      </Link>
                    </td>
                    <td>{formatDate(client.fy_start)}</td>
                    <td>{formatDate(client.created_at)}</td>
                    <td className="num">
                      <Link to={`/clients/${client.id}/review`}>Review queue →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {creating && (
        <NewClient
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            reload()
          }}
        />
      )}
    </>
  )
}

function NewClient({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const year = new Date().getMonth() >= 3 ? new Date().getFullYear() : new Date().getFullYear() - 1
  const [name, setName] = useState('')
  const [fyStart, setFyStart] = useState(`${year}-04-01`)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`${V1}/clients/`, { name: name.trim(), fy_start: fyStart })
      onCreated()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="New client" onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Name" hint="As it should appear on reports and in Tally.">
          <input type="text" required value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Financial year starts" hint="Normally 1 April. Indian FY runs April to March.">
          <input type="date" required value={fyStart} onChange={(e) => setFyStart(e.target.value)} />
        </Field>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Create
          </Button>
        </div>
      </form>
    </Modal>
  )
}
