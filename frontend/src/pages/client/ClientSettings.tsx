import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, V1 } from '../../api/client'
import type { Client } from '../../api/types'
import { Button, ErrorNote, Field, Note, useAsync } from '../../components/ui'
import { teamApi } from '../team/api'

export default function ClientSettings({ client, onChanged }: { client: Client; onChanged: () => void }) {
  const navigate = useNavigate()
  const [name, setName] = useState(client.name)
  const [fyStart, setFyStart] = useState(client.fy_start)
  const [profile, setProfile] = useState(client.business_profile ?? '')
  const [lead, setLead] = useState(client.lead?.id ?? '')
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [typed, setTyped] = useState('')
  const leads = useAsync(() => teamApi.members({ from: new Date().toISOString().slice(0, 10), to: new Date().toISOString().slice(0, 10) }), [])

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const body: Record<string, string> = {}
      if (name.trim() !== client.name) body.name = name.trim()
      if (fyStart !== client.fy_start) body.fy_start = fyStart
      if (profile.trim() !== (client.business_profile ?? '')) body.business_profile = profile.trim()
      if (Object.keys(body).length) await api.patch(`${V1}/clients/${client.id}/`, body)
      if (lead !== (client.lead?.id ?? '')) await teamApi.setLead(client.id, lead || null)
      setSaved(true)
      onChanged()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await api.delete(`${V1}/clients/${client.id}/`)
      navigate('/clients', { replace: true })
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <div className="grid-2">
      <div className="panel">
        <div className="panel-head">
          <h2>Client details</h2>
        </div>
        <form className="panel-body" onSubmit={save}>
          <ErrorNote error={error} />
          {saved && <Note tone="good">Saved.</Note>}
          <Field label="Name" hint="As it should appear on reports and in Tally.">
            <input type="text" required value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Financial year starts" hint="Normally 1 April. Can't change once entries are posted.">
            <input type="date" required value={fyStart} onChange={(e) => setFyStart(e.target.value)} />
          </Field>
          <Field
            label="What the business does"
            hint="A few sentences: what it sells or does, who pays it, what it spends on, any staff, rent or loans. The ledger-suggesting model reads this to book better. Don't put names, PAN, GSTIN or account numbers here."
          >
            <textarea
              rows={5}
              maxLength={2000}
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
              placeholder="e.g. Wholesale cloth trader. Sells to retailers on 30-day credit, buys from mills in Surat, rents a godown, two salaried staff, one vehicle loan."
            />
          </Field>
          <Field label="Lead" hint="The Senior CA responsible for this client, and the one who signs off its entries.">
            <select value={lead} onChange={(e) => setLead(e.target.value)}>
              <option value="">No lead (any Senior CA who can see it may sign off)</option>
              {leads.data?.leads.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name} ({person.role_display})
                </option>
              ))}
            </select>
          </Field>
          <div className="row end">
            <Button kind="primary" type="submit" busy={busy}>
              Save changes
            </Button>
          </div>
        </form>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Delete client</h2>
        </div>
        <div className="panel-body stack">
          <p className="sub">
            Deletes the client with its statements, ledgers, rules and assignments. A client with posted entries can't be deleted: the books are
            permanent.
          </p>
          {deleting ? (
            <>
              <Field label={`Type ${client.name} to confirm`}>
                <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
              </Field>
              <div className="row end">
                <Button onClick={() => setDeleting(false)}>Cancel</Button>
                <Button kind="danger" busy={busy} disabled={typed !== client.name} onClick={() => void remove()}>
                  Delete {client.name}
                </Button>
              </div>
            </>
          ) : (
            <div className="row end">
              <Button kind="danger" onClick={() => setDeleting(true)}>
                Delete client…
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
