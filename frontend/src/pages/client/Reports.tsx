// Trial balance, P&L, balance sheet, and the month-end check. Every report
// states how many rows are still unposted; a report over incomplete books is
// not wrong, but handing one to a client without knowing that is.

import { useState } from 'react'
import { allPages, api, V1 } from '../../api/client'
import type { BalanceCheck, BalanceSheet, BankAccount, Client, LedgerBalance, ProfitAndLoss, ReportFooter, TrialBalance } from '../../api/types'
import { Badge, Button, ErrorNote, formatDate, Money, Note, Spinner, useAsync } from '../../components/ui'

function currentFy(): number {
  const now = new Date()
  return now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
}

export default function Reports({ client }: { client: Client }) {
  const [fy, setFy] = useState(currentFy())
  const [tab, setTab] = useState<'tb' | 'pl' | 'bs' | 'recon'>('tb')
  const years = Array.from({ length: 6 }, (_, i) => currentFy() - i)

  return (
    <>
      <div className="row between">
        <div className="row">
          <Button kind={tab === 'tb' ? 'primary' : 'default'} onClick={() => setTab('tb')}>
            Trial balance
          </Button>
          <Button kind={tab === 'pl' ? 'primary' : 'default'} onClick={() => setTab('pl')}>
            Profit &amp; loss
          </Button>
          <Button kind={tab === 'bs' ? 'primary' : 'default'} onClick={() => setTab('bs')}>
            Balance sheet
          </Button>
          <Button kind={tab === 'recon' ? 'primary' : 'default'} onClick={() => setTab('recon')}>
            Month-end check
          </Button>
        </div>
        {tab !== 'recon' && (
          <label className="row">
            <span className="sub">Financial year</span>
            <select value={fy} onChange={(e) => setFy(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}-{String(y + 1).slice(2)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="mt" />
      {tab === 'tb' && <TB client={client} fy={fy} />}
      {tab === 'pl' && <PL client={client} fy={fy} />}
      {tab === 'bs' && <BS client={client} fy={fy} />}
      {tab === 'recon' && <Reconciliation client={client} />}
    </>
  )
}

function Footer({ footer }: { footer: ReportFooter }) {
  return (
    <>
      {!footer.is_complete && (
        <Note tone="warn">
          <strong>INCOMPLETE:</strong> {footer.pending_review} transaction(s) are classified but not approved and are not in these figures.
        </Note>
      )}
      <div className="caption">
        {footer.client_name} · FY {footer.fy_label} · {formatDate(footer.period_start)} – {formatDate(footer.period_end)} · {footer.entry_count} entries
      </div>
    </>
  )
}

function Rows({ rows, closing }: { rows: LedgerBalance[]; closing?: boolean }) {
  return (
    <>
      {rows.map((r) => (
        <tr key={r.name}>
          <td>
            {r.name}
            <div className="tiny">{r.group.replace(/_/g, ' ').toLowerCase()}</div>
          </td>
          <td className="num">
            <Money value={closing ? r.closing_debit_display : r.debit_display} muted={closing ? r.closing_debit_paise === 0 : r.debit_paise === 0} />
          </td>
          <td className="num">
            <Money value={closing ? r.closing_credit_display : r.credit_display} muted={closing ? r.closing_credit_paise === 0 : r.credit_paise === 0} />
          </td>
        </tr>
      ))}
    </>
  )
}

function TB({ client, fy }: { client: Client; fy: number }) {
  const { data, error, loading } = useAsync(() => api.get<TrialBalance>(`${V1}/clients/${client.id}/reports/trial-balance/?fy=${fy}`), [client.id, fy])
  if (loading) return <Spinner />
  if (error || !data) return <ErrorNote error={error} />
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Trial balance</h2>
        {data.balances ? <Badge tone="good">Balances</Badge> : <Badge tone="bad">Does not balance</Badge>}
      </div>
      <div className="panel-body">
        <Footer footer={data.footer} />
      </div>
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>Ledger</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
            </tr>
          </thead>
          <tbody>
            <Rows rows={data.rows} closing />
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="num">
                <Money value={data.total_debit_display} />
              </td>
              <td className="num">
                <Money value={data.total_credit_display} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

function PL({ client, fy }: { client: Client; fy: number }) {
  const { data, error, loading } = useAsync(() => api.get<ProfitAndLoss>(`${V1}/clients/${client.id}/reports/profit-and-loss/?fy=${fy}`), [client.id, fy])
  if (loading) return <Spinner />
  if (error || !data) return <ErrorNote error={error} />
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Profit &amp; loss</h2>
        <Badge tone={data.net_profit_paise >= 0 ? 'good' : 'bad'}>
          Net {data.net_profit_paise >= 0 ? 'profit' : 'loss'}: {data.net_profit_display}
        </Badge>
      </div>
      <div className="panel-body">
        <Footer footer={data.footer} />
      </div>
      <div className="grid-2">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Expenses</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
              </tr>
            </thead>
            <tbody>
              <Rows rows={data.expenses} closing />
            </tbody>
            <tfoot>
              <tr>
                <td>Total expenses</td>
                <td className="num" colSpan={2}>
                  <Money value={data.total_expenses_display} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Income</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
              </tr>
            </thead>
            <tbody>
              <Rows rows={data.income} closing />
            </tbody>
            <tfoot>
              <tr>
                <td>Total income</td>
                <td className="num" colSpan={2}>
                  <Money value={data.total_income_display} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  )
}

function BS({ client, fy }: { client: Client; fy: number }) {
  const { data, error, loading } = useAsync(() => api.get<BalanceSheet>(`${V1}/clients/${client.id}/reports/balance-sheet/?fy=${fy}`), [client.id, fy])
  if (loading) return <Spinner />
  if (error || !data) return <ErrorNote error={error} />
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Balance sheet</h2>
        <div className="pill-row">
          {data.balances ? <Badge tone="good">Balances</Badge> : <Badge tone="bad">Does not balance</Badge>}
          {data.suspense_paise !== 0 && <Badge tone="warn">Suspense: {data.suspense_display}</Badge>}
        </div>
      </div>
      <div className="panel-body">
        <Footer footer={data.footer} />
      </div>
      <div className="grid-2">
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Liabilities</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
              </tr>
            </thead>
            <tbody>
              <Rows rows={data.liabilities} closing />
              <tr>
                <td>Net {data.net_profit_paise >= 0 ? 'profit' : 'loss'} for the year</td>
                <td className="num" colSpan={2}>
                  <Money value={data.net_profit_display} />
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="num" colSpan={2}>
                  <Money value={data.total_liabilities_display} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>Assets</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
              </tr>
            </thead>
            <tbody>
              <Rows rows={data.assets} closing />
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="num" colSpan={2}>
                  <Money value={data.total_assets_display} />
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  )
}

function Reconciliation({ client }: { client: Client }) {
  const accounts = useAsync(() => allPages<BankAccount>(`${V1}/clients/${client.id}/bank-accounts/`), [client.id])
  const [account, setAccount] = useState('')
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10))
  const [check, setCheck] = useState<BalanceCheck | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const chosen = account || accounts.data?.[0]?.id || ''

  async function run() {
    setBusy(true)
    setError(null)
    setCheck(null)
    try {
      setCheck(await api.get<BalanceCheck>(`${V1}/bank-accounts/${chosen}/reconciliation/?as_of=${asOf}`))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Does the bank ledger agree with the bank?</h2>
      </div>
      <div className="panel-body">
        <p className="sub">
          The computed bank-ledger balance beside the statement's own figure at a date. One subtraction that catches a row posted twice, a correction reversed the wrong way, an entry approved against the wrong account. A period that does not reconcile is not finished.
        </p>
        <div className="inline-form">
          <label className="field">
            <span className="field-label">Bank account</span>
            <select value={chosen} onChange={(e) => setAccount(e.target.value)}>
              {(accounts.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">As of</span>
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </label>
          <Button kind="primary" onClick={() => void run()} busy={busy} disabled={!chosen}>
            Check
          </Button>
        </div>
        <ErrorNote error={error} />
        {check && (
          <>
            <div className="grid-cards">
              <div className="card">
                <div className="k">Books say</div>
                <div className="v small">
                  <Money value={check.ledger_balance_display} />
                </div>
              </div>
              <div className="card">
                <div className="k">Bank says</div>
                <div className="v small">
                  <Money value={check.statement_balance_display} />
                </div>
              </div>
              <div className="card">
                <div className="k">Difference</div>
                <div className={`v small ${check.matches ? 'cr' : 'dr'}`}>
                  <Money value={check.difference_display} />
                </div>
              </div>
              <div className="card">
                <div className="k">Unapproved to date</div>
                <div className="v small">{check.unapproved_count}</div>
              </div>
            </div>
            <Note tone={check.can_close ? 'good' : check.matches ? 'warn' : 'bad'}>{check.explanation}</Note>
          </>
        )}
      </div>
    </div>
  )
}
