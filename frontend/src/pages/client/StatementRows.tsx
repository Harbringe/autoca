// A statement's rows exactly as the bank printed them, with what became of
// each. This is the screen to open beside the original PDF when checking a
// new bank's format: read down, and the running balance should agree on
// every row.

import { Link, useParams } from 'react-router-dom'
import { allPages, api, V1 } from '../../api/client'
import type { Classification, Client, Statement, TallyExport, Transaction } from '../../api/types'
import { Badge, Button, ErrorNote, formatDate, Money, Note, Spinner, useAsync } from '../../components/ui'
import { useState } from 'react'

export default function StatementRows({ client }: { client: Client }) {
  const { statementId = '' } = useParams()
  const statement = useAsync(() => api.get<Statement>(`${V1}/clients/${client.id}/statements/${statementId}/`), [statementId])
  const rows = useAsync(() => allPages<Transaction>(`${V1}/clients/${client.id}/statements/${statementId}/transactions/`), [statementId])
  const classifications = useAsync(
    async () => {
      const all = await allPages<Classification>(`${V1}/classifications/?statement=${statementId}`)
      return new Map(all.map((c) => [c.transaction.id, c]))
    },
    [statementId],
  )
  const [tally, setTally] = useState<TallyExport | null>(null)
  const [tallyError, setTallyError] = useState<unknown>(null)

  async function exportTally() {
    setTallyError(null)
    try {
      setTally(await api.get<TallyExport>(`${V1}/statements/${statementId}/tally-export/`))
    } catch (err) {
      setTallyError(err)
    }
  }

  function download() {
    if (!tally) return
    const blob = new Blob([tally.xml], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${client.name.replace(/[^A-Za-z0-9]+/g, '_')}_${statement.data?.period_start}_${statement.data?.period_end}.xml`
    a.click()
    URL.revokeObjectURL(url)
  }

  const s = statement.data
  return (
    <>
      <div className="row between">
        <div>
          <Link to={`/clients/${client.id}`}>← All statements</Link>
          {s && (
            <h2>
              {s.bank_account_label} · {formatDate(s.period_start)} – {formatDate(s.period_end)}
            </h2>
          )}
        </div>
        <div className="row">
          <Button onClick={() => void exportTally()}>Tally XML (approved only)</Button>
        </div>
      </div>

      <ErrorNote error={statement.error ?? rows.error ?? tallyError} />

      {tally && (
        <Note tone={tally.unapproved ? 'warn' : 'good'}>
          <strong>
            {tally.voucher_count} vouchers, {tally.ledger_count} ledger masters.
          </strong>{' '}
          {tally.unapproved > 0 && <>{tally.unapproved} classified rows are not approved and were left out. </>}
          <Button className="btn-sm" kind="primary" onClick={download}>
            Download XML
          </Button>
          <pre className="xml">{tally.xml.slice(0, 4000)}{tally.xml.length > 4000 ? '\n…' : ''}</pre>
        </Note>
      )}

      {s && (
        <div className="grid-cards">
          <div className="card">
            <div className="k">Opening</div>
            <div className="v small">
              <Money value={s.opening_balance_display} />
            </div>
          </div>
          <div className="card">
            <div className="k">Total debits</div>
            <div className="v small dr">
              <Money value={s.total_debit_display} />
            </div>
          </div>
          <div className="card">
            <div className="k">Total credits</div>
            <div className="v small cr">
              <Money value={s.total_credit_display} />
            </div>
          </div>
          <div className="card">
            <div className="k">Closing</div>
            <div className="v small">
              <Money value={s.closing_balance_display} />
            </div>
          </div>
          <div className="card">
            <div className="k">Rows</div>
            <div className="v small">{s.transaction_count}</div>
          </div>
        </div>
      )}

      <div className="panel">
        {rows.loading ? (
          <Spinner />
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Date</th>
                  <th>Particulars (as printed)</th>
                  <th className="num">Debit</th>
                  <th className="num">Credit</th>
                  <th className="num">Balance</th>
                  <th>Placed in</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(rows.data ?? []).map((row) => {
                  const c = classifications.data?.get(row.id)
                  return (
                    <tr key={row.id}>
                      <td className="num tiny">{row.row_number}</td>
                      <td>{formatDate(row.value_date)}</td>
                      <td className="narr mono">{row.narration}</td>
                      <td className="num dr">{row.debit_paise ? <Money value={row.debit_display} /> : ''}</td>
                      <td className="num cr">{row.credit_paise ? <Money value={row.credit_display} /> : ''}</td>
                      <td className="num">
                        <Money value={row.balance_display} />
                      </td>
                      <td>
                        {c?.ledger_name ?? <span className="tiny">—</span>}
                        {c?.party_name && <div className="tiny">{c.party_name}</div>}
                      </td>
                      <td>
                        {!c ? (
                          <Badge>Not classified</Badge>
                        ) : c.is_posted ? (
                          <Badge tone="good">Posted</Badge>
                        ) : c.ledger ? (
                          <Badge tone="warn">Awaiting approval</Badge>
                        ) : (
                          <Badge tone="bad">Unresolved</Badge>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
