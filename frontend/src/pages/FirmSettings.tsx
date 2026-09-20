import { useState, type FormEvent } from 'react'
import { api, V1 } from '../api/client'
import { useSession } from '../auth/session'
import { Badge, Button, ErrorNote, Field, formatDate, Note, Spinner, useAsync } from '../components/ui'

interface PersonRef {
  id: string
  name: string
  role_display: string
  is_owner: boolean
}

interface FirmDetails {
  id: string
  name: string
  created_at: string
  owner: PersonRef | null
  admins: PersonRef[]
  counts: { active_members: number; senior_cas: number; staff: number; clients: number }
  can: { rename: boolean; transfer: boolean }
}

export default function FirmSettings() {
  const { refresh } = useSession()
  const { data, error, loading, reload } = useAsync(() => api.get<FirmDetails>(`${V1}/firm/`), [])
  const [name, setName] = useState<string | null>(null)
  const [newOwner, setNewOwner] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)

  if (loading && !data) return <Spinner />
  if (!data) return <ErrorNote error={error} />

  async function rename(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setActionError(null)
    setSaved('')
    try {
      await api.patch(`${V1}/firm/`, { name: (name ?? data!.name).trim() })
      setName(null)
      setSaved('Firm renamed.')
      reload()
      await refresh()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  async function transfer() {
    setBusy(true)
    setActionError(null)
    setSaved('')
    try {
      await api.post(`${V1}/firm/owner/`, { member: newOwner })
      setConfirming(false)
      setNewOwner('')
      setSaved('Ownership transferred.')
      reload()
      await refresh()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  const candidates = data.admins.filter((a) => !a.is_owner)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Firm settings</h1>
          <p className="sub">On AutoCA since {formatDate(data.created_at)}.</p>
        </div>
      </div>
      <ErrorNote error={actionError} />
      {saved && <Note tone="good">{saved}</Note>}

      <div className="grid-cards">
        <div className="card">
          <div className="k">People</div>
          <div className="v">{data.counts.active_members}</div>
        </div>
        <div className="card">
          <div className="k">Senior CAs</div>
          <div className="v">{data.counts.senior_cas}</div>
        </div>
        <div className="card">
          <div className="k">Staff &amp; read-only</div>
          <div className="v">{data.counts.staff}</div>
        </div>
        <div className="card">
          <div className="k">Clients</div>
          <div className="v">{data.counts.clients}</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Firm name</h2>
          </div>
          <form className="panel-body" onSubmit={rename}>
            <Field label="Name" hint="Shown to everyone in the firm, and on reports.">
              <input type="text" required value={name ?? data.name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <div className="row end">
              <Button kind="primary" type="submit" busy={busy} disabled={name === null || name.trim() === data.name}>
                Save
              </Button>
            </div>
          </form>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Ownership</h2>
          </div>
          <div className="panel-body stack">
            <p>
              {data.owner ? (
                <>
                  <strong>{data.owner.name}</strong> <Badge tone="info">Firm owner</Badge>
                </>
              ) : (
                <Badge tone="warn">This firm has no owner yet</Badge>
              )}
            </p>
            <p className="sub">
              The owner is the only one who can add or remove firm administrators and hand ownership on. Administrators
              otherwise have the same powers.
            </p>
            <div>
              <strong>Administrators:</strong> {data.admins.map((a) => a.name).join(', ') || 'none'}
            </div>
            {data.can.transfer &&
              (candidates.length ? (
                <div className="stack">
                  <Field
                    label={data.owner ? 'Transfer ownership to' : 'Make someone the owner'}
                    hint="Only a firm administrator can own the firm. You stay an administrator."
                  >
                    <select value={newOwner} onChange={(e) => setNewOwner(e.target.value)}>
                      <option value="">Choose an administrator…</option>
                      {candidates.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {confirming ? (
                    <div className="row">
                      <span className="sub">You won't be able to undo this yourself.</span>
                      <Button kind="danger" busy={busy} onClick={() => void transfer()}>
                        Confirm transfer
                      </Button>
                      <Button onClick={() => setConfirming(false)}>Cancel</Button>
                    </div>
                  ) : (
                    <div className="row end">
                      <Button disabled={!newOwner} onClick={() => setConfirming(true)}>
                        {data.owner ? 'Transfer ownership…' : 'Make owner…'}
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <p className="sub">To hand ownership on, first make someone a firm administrator from the Team page.</p>
              ))}
          </div>
        </div>
      </div>
    </>
  )
}
