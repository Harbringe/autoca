import { useState, type FormEvent } from 'react'
import { allPages, api, V1 } from '../../api/client'
import type { Client, LedgerAccount } from '../../api/types'
import { LEDGER_GROUPS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, Modal, Note, Spinner, useAsync } from '../../components/ui'

const groupLabel = (value: string) => LEDGER_GROUPS.find((g) => g.value === value)?.label ?? value

export default function ChartOfAccounts({ client }: { client: Client }) {
  const { can } = useSession()
  const ledgers = useAsync(() => allPages<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`), [client.id])
  const [name, setName] = useState('')
  const [group, setGroup] = useState('INDIRECT_EXPENSE')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [accepting, setAccepting] = useState<LedgerAccount | null>(null)
  const [merging, setMerging] = useState<LedgerAccount | null>(null)

  const all = ledgers.data ?? []
  const inUse = all.filter((l) => l.status === 'ACTIVE')
  const proposals = all.filter((l) => l.status === 'PROPOSED')
  const canDecide = can('journal.approve') && client.can_sign_off

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy('create')
    setError(null)
    try {
      await api.post(`${V1}/clients/${client.id}/ledgers/`, { name: name.trim(), group })
      setName('')
      ledgers.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  async function toggle(ledger: LedgerAccount) {
    setError(null)
    try {
      await api.patch(`${V1}/clients/${client.id}/ledgers/${ledger.id}/`, { is_active: !ledger.is_active })
      ledgers.reload()
    } catch (err) {
      setError(err)
    }
  }

  async function reject(ledger: LedgerAccount) {
    setBusy(ledger.id)
    setError(null)
    try {
      const r = await api.post<{ released: number }>(`${V1}/clients/${client.id}/ledgers/${ledger.id}/reject/`)
      setFlash(`Rejected “${ledger.name}”. ${r.released} row${r.released === 1 ? '' : 's'} went back to the review queue, and it won’t be proposed again.`)
      ledgers.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  const grouped = LEDGER_GROUPS.map((g) => ({ ...g, items: inUse.filter((l) => l.group === g.value) })).filter((g) => g.items.length)

  return (
    <>
      <ErrorNote error={error ?? ledgers.error} />
      {flash && <Note tone="good">{flash}</Note>}

      {proposals.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h2>Proposed by AI</h2>
            <span className="sub">
              {proposals.length} new ledger{proposals.length === 1 ? '' : 's'} · {canDecide ? 'your decision' : 'waiting for a Senior CA'}
            </span>
          </div>
          <div className="panel-body">
            <p className="sub">
              The AI found transactions that don’t fit any existing ledger. Nothing can be approved into these until a CA accepts them. Rename on acceptance if the client’s Tally uses a different name, or merge into a ledger they already have.
            </p>
          </div>
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Proposed ledger</th>
                  <th>Group</th>
                  <th className="num">Rows</th>
                  <th>Why</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {proposals.map((l) => (
                  <tr key={l.id}>
                    <td>
                      <strong>{l.name}</strong>
                    </td>
                    <td>{groupLabel(l.group)}</td>
                    <td className="num">{l.row_count}</td>
                    <td className="rationale">{l.proposal_reason ? `“${l.proposal_reason}”` : '—'}</td>
                    <td className="num">
                      {canDecide && (
                        <div className="row end">
                          <Button className="btn-sm" kind="primary" onClick={() => setAccepting(l)} disabled={!!busy}>
                            Accept
                          </Button>
                          <Button className="btn-sm" onClick={() => setMerging(l)} disabled={!!busy}>
                            Merge
                          </Button>
                          <Button className="btn-sm" kind="ghost" onClick={() => void reject(l)} busy={busy === l.id} disabled={!!busy}>
                            Reject
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {can('ledger.manage') && (
        <div className="panel">
          <div className="panel-head">
            <h2>Add a ledger head</h2>
          </div>
          <div className="panel-body">
            <form className="inline-form" onSubmit={create}>
              <Field label="Name" hint="Exactly as it is named in the client's Tally company.">
                <input id="new-ledger-name" type="text" required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Group">
                <select id="new-ledger-group" value={group} onChange={(e) => setGroup(e.target.value)}>
                  {LEDGER_GROUPS.map((g) => (
                    <option key={g.value} value={g.value}>
                      {g.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Button kind="primary" type="submit" busy={busy === 'create'}>
                Add
              </Button>
            </form>
          </div>
        </div>
      )}
      <div className="panel">
        <div className="panel-head">
          <h2>Chart of accounts</h2>
          <span className="sub">{inUse.length} ledgers</span>
        </div>
        {ledgers.loading ? (
          <Spinner />
        ) : !grouped.length ? (
          <Empty title="No ledgers yet">Bank Charges, Bank Interest Received and the bank account's own ledger are created on the first upload. Add the rest here or while placing rows.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Ledger</th>
                  <th>Group</th>
                  <th></th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {grouped.map((g) =>
                  g.items.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <strong>{l.name}</strong>
                      </td>
                      <td>{g.label}</td>
                      <td>
                        {!l.is_active && <Badge>Inactive</Badge>}
                        {l.is_bank_or_cash && <Badge tone="info">Bank / cash</Badge>}
                      </td>
                      <td className="num">
                        {can('ledger.manage') && (
                          <Button className="btn-sm" onClick={() => void toggle(l)}>
                            {l.is_active ? 'Deactivate' : 'Reactivate'}
                          </Button>
                        )}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {accepting && (
        <AcceptProposal
          client={client}
          ledger={accepting}
          onClose={() => setAccepting(null)}
          onDone={(accepted) => {
            setAccepting(null)
            setFlash(`Accepted “${accepted.name}”. Its ${accepted.row_count} suggested row${accepted.row_count === 1 ? '' : 's'} can now be reviewed and approved in the review queue.`)
            ledgers.reload()
          }}
        />
      )}
      {merging && (
        <MergeProposal
          client={client}
          ledger={merging}
          targets={inUse.filter((l) => l.is_active && !l.is_bank_or_cash)}
          onClose={() => setMerging(null)}
          onDone={(moved, into) => {
            setMerging(null)
            setFlash(`Merged into “${into}”. ${moved} row${moved === 1 ? '' : 's'} moved; the proposal is gone.`)
            ledgers.reload()
          }}
        />
      )}
    </>
  )
}

function AcceptProposal({ client, ledger, onClose, onDone }: { client: Client; ledger: LedgerAccount; onClose: () => void; onDone: (l: LedgerAccount) => void }) {
  const [name, setName] = useState(ledger.name)
  const [group, setGroup] = useState<string>(ledger.group)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(await api.post<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/${ledger.id}/accept/`, { name: name.trim(), group }))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Accept proposed ledger" onClose={onClose}>
      {ledger.proposal_reason && <p className="rationale">AI’s reason: “{ledger.proposal_reason}”</p>}
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Ledger name" hint="Change it to match the client's Tally company exactly, or Tally will create a second ledger.">
          <input id="accept-ledger-name" type="text" required value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Group">
          <select id="accept-ledger-group" value={group} onChange={(e) => setGroup(e.target.value)}>
            {LEDGER_GROUPS.filter((g) => !['BANK', 'CASH', 'SUSPENSE'].includes(g.value)).map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
        </Field>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Accept ledger
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function MergeProposal({ client, ledger, targets, onClose, onDone }: { client: Client; ledger: LedgerAccount; targets: LedgerAccount[]; onClose: () => void; onDone: (moved: number, into: string) => void }) {
  const [into, setInto] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await api.post<{ moved: number }>(`${V1}/clients/${client.id}/ledgers/${ledger.id}/merge/`, { into })
      onDone(r.moved, targets.find((t) => t.id === into)?.name ?? '')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Merge “${ledger.name}” into an existing ledger`} onClose={onClose}>
      <p className="sub">Use this when the client already has the right ledger under another name. The {ledger.row_count} suggested row{ledger.row_count === 1 ? '' : 's'} move across, still as suggestions.</p>
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Merge into">
          <select id="merge-into" required value={into} onChange={(e) => setInto(e.target.value)} autoFocus>
            <option value="">— choose —</option>
            {LEDGER_GROUPS.map((g) => ({ ...g, items: targets.filter((t) => t.group === g.value) }))
              .filter((g) => g.items.length)
              .map((g) => (
                <optgroup key={g.value} label={g.label}>
                  {g.items.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </optgroup>
              ))}
          </select>
        </Field>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Merge
          </Button>
        </div>
      </form>
    </Modal>
  )
}
