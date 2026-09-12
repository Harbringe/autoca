import { useState, type FormEvent } from 'react'
import { allPages, api, V1 } from '../../api/client'
import type { Client, LedgerAccount } from '../../api/types'
import { LEDGER_GROUPS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, Spinner, useAsync } from '../../components/ui'

export default function ChartOfAccounts({ client }: { client: Client }) {
  const { can } = useSession()
  const ledgers = useAsync(() => allPages<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`), [client.id])
  const [name, setName] = useState('')
  const [group, setGroup] = useState('INDIRECT_EXPENSE')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`${V1}/clients/${client.id}/ledgers/`, { name: name.trim(), group })
      setName('')
      ledgers.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
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

  const grouped = LEDGER_GROUPS.map((g) => ({ ...g, items: (ledgers.data ?? []).filter((l) => l.group === g.value) })).filter((g) => g.items.length)

  return (
    <>
      {can('ledger.manage') && (
        <div className="panel">
          <div className="panel-head">
            <h2>Add a ledger head</h2>
          </div>
          <div className="panel-body">
            <form className="inline-form" onSubmit={create}>
              <Field label="Name" hint="Exactly as it is named in the client's Tally company.">
                <input type="text" required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Group">
                <select value={group} onChange={(e) => setGroup(e.target.value)}>
                  {LEDGER_GROUPS.map((g) => (
                    <option key={g.value} value={g.value}>
                      {g.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Button kind="primary" type="submit" busy={busy}>
                Add
              </Button>
            </form>
            <ErrorNote error={error} />
          </div>
        </div>
      )}
      <div className="panel">
        <div className="panel-head">
          <h2>Chart of accounts</h2>
          <span className="sub">{ledgers.data?.length ?? 0} ledgers</span>
        </div>
        <ErrorNote error={ledgers.error} />
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
                      <td>{!l.is_active && <Badge>Inactive</Badge>}{l.is_bank_or_cash && <Badge tone="info">Bank / cash</Badge>}</td>
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
    </>
  )
}
