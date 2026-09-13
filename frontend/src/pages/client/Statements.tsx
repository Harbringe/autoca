// A client's bank accounts and the statements on file, plus the upload.
//
// Upload answers 202 with a job; the job result says what happened -- rows
// read, rows already present, whether an opening balance still needs
// confirming, how many rows the rules and the model placed. Everything the
// person needs to decide what to do next is on this screen when it finishes.

import { useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { allPages, api, V1, waitForJob } from '../../api/client'
import type { BankAccount, Client, Job, Statement } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, formatDate, Modal, Money, Note, Spinner, useAsync } from '../../components/ui'
import { RecategorizeButton, type Flash } from './Recategorize'

export default function Statements({ client }: { client: Client }) {
  const { can } = useSession()
  const accounts = useAsync(() => allPages<BankAccount>(`${V1}/clients/${client.id}/bank-accounts/`), [client.id])
  const statements = useAsync(() => allPages<Statement>(`${V1}/clients/${client.id}/statements/`), [client.id])
  const [confirming, setConfirming] = useState<BankAccount | null>(null)
  const [flash, setFlash] = useState<Flash | null>(null)

  const reload = () => {
    accounts.reload()
    statements.reload()
  }

  const needsOpening = (accounts.data ?? []).filter((a) => !a.has_opening_balance)

  return (
    <>
      {can('document.upload') && <Upload client={client} onDone={reload} />}

      {needsOpening.length > 0 && (
        <Note tone="warn">
          <strong>Opening balance not confirmed</strong> for {needsOpening.map((a) => a.label).join(', ')}. Month-end reconciliation is not meaningful until it is.{' '}
          {can('ledger.manage') && (
            <Button kind="ghost" className="btn-sm" onClick={() => setConfirming(needsOpening[0])}>
              Confirm now
            </Button>
          )}
        </Note>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Bank accounts</h2>
        </div>
        <ErrorNote error={accounts.error} />
        {accounts.loading ? (
          <Spinner />
        ) : !accounts.data?.length ? (
          <Empty title="No accounts yet">Accounts are created from the statements you upload — the account number is read from the file.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Bank</th>
                  <th>IFSC</th>
                  <th>Tally ledger</th>
                  <th className="num">Opening balance</th>
                  <th>As of</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.map((account) => (
                  <tr key={account.id}>
                    <td>
                      <strong>••••{account.account_last4}</strong>
                    </td>
                    <td>{account.bank_code}</td>
                    <td className="mono">{account.ifsc || '—'}</td>
                    <td>{account.ledger_name}</td>
                    <td className="num">
                      {account.has_opening_balance ? <Money value={account.opening_balance_display} /> : <Badge tone="warn">Not confirmed</Badge>}
                    </td>
                    <td>{formatDate(account.opening_as_of)}</td>
                    <td className="num">
                      {can('ledger.manage') && (
                        <Button className="btn-sm" onClick={() => setConfirming(account)}>
                          {account.has_opening_balance ? 'Change' : 'Confirm'} opening balance
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Statements</h2>
        </div>
        <ErrorNote error={statements.error} />
        {flash && <Note tone={flash.tone}>{flash.text}</Note>}
        {statements.loading ? (
          <Spinner />
        ) : !statements.data?.length ? (
          <Empty title="No statements yet">Upload the client's first bank statement above.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Account</th>
                  <th>File</th>
                  <th className="num">Rows</th>
                  <th className="num">Opening</th>
                  <th className="num">Debits</th>
                  <th className="num">Credits</th>
                  <th className="num">Closing</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {statements.data.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {formatDate(s.period_start)} – {formatDate(s.period_end)}
                    </td>
                    <td>{s.bank_account_label}</td>
                    <td>
                      <div>{s.document.original_filename || '—'}</div>
                      <div className="tiny">
                        {s.document.page_count} pages · {s.parser} v{s.parser_version}
                      </div>
                    </td>
                    <td className="num">{s.transaction_count}</td>
                    <td className="num">
                      <Money value={s.opening_balance_display} />
                    </td>
                    <td className="num dr">
                      <Money value={s.total_debit_display} />
                    </td>
                    <td className="num cr">
                      <Money value={s.total_credit_display} />
                    </td>
                    <td className="num">
                      <Money value={s.closing_balance_display} />
                    </td>
                    <td className="num">
                      <div className="row end">
                        {can('transaction.classify') && <RecategorizeButton client={client} statementId={s.id} onResult={setFlash} />}
                        <Link to={`/clients/${client.id}/statements/${s.id}`}>Rows →</Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {confirming && (
        <OpeningBalance
          client={client}
          account={confirming}
          onClose={() => setConfirming(null)}
          onDone={() => {
            setConfirming(null)
            reload()
          }}
        />
      )}
    </>
  )
}

function Upload({ client, onDone }: { client: Client; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [allowGap, setAllowGap] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function send(file: File) {
    setBusy(true)
    setError(null)
    setJob(null)
    const form = new FormData()
    form.append('file', file)
    form.append('allow_gap', allowGap ? 'true' : 'false')
    try {
      const started = await api.post<Job>(`${V1}/clients/${client.id}/statements/upload/`, form)
      setJob(started)
      const finished = await waitForJob(started, setJob)
      setJob(finished)
      if (finished.status === 'SUCCEEDED') onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const result = job?.status === 'SUCCEEDED' ? (job.result as Record<string, number | boolean | string>) : null

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Upload a statement</h2>
        <label className="check">
          <input type="checkbox" checked={allowGap} onChange={(e) => setAllowGap(e.target.checked)} />
          Accept a gap from the previous statement (a missing period)
        </label>
      </div>
      <div className="panel-body">
        <label
          className={over ? 'dropzone over' : 'dropzone'}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            const file = e.dataTransfer.files[0]
            if (file) void send(file)
          }}
        >
          <input ref={input} type="file" accept="application/pdf,.pdf" disabled={busy} onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])} />
          {busy ? (
            <Spinner label={job?.message || 'Reading the statement…'} />
          ) : (
            <>
              <strong>Drop a bank statement PDF here, or click to choose.</strong>
              <div className="tiny">Any bank. The account is read from the file. Up to 25 MB.</div>
            </>
          )}
        </label>
        <ErrorNote error={error} className="mt" />
        {job?.status === 'FAILED' && (
          <Note tone="bad">
            <strong>Could not read this statement</strong> <Badge tone="bad">{job.error_code}</Badge>
            <div>{job.error}</div>
          </Note>
        )}
        {result && (
          <Note tone={result.is_new ? 'good' : 'info'}>
            {result.is_new ? (
              <>
                <strong>Read {String(result.rows_created)} rows</strong>
                {Number(result.rows_already_present) > 0 && <> ({String(result.rows_already_present)} already on file from an overlapping statement)</>}. Rules placed{' '}
                {String(result.suggested)}; the model suggested {String(result.model_suggested ?? 0)}; {String(result.queued_for_review)} went to the queue.
                {Number(result.model_proposed) > 0 && <div>The model proposed {String(result.model_proposed)} new ledger(s). A CA can accept or reject them under Chart of accounts.</div>}
                {result.model_error ? <div className="tiny">Model tier: {String(result.model_error)}</div> : null}
                {result.needs_opening_confirmation ? <div>This account's opening balance still needs confirming.</div> : null}
              </>
            ) : (
              <>
                <strong>This file was already on file.</strong> Nothing was re-read; the original statement is shown below.
              </>
            )}
            <div>
              <Link to={`/clients/${client.id}/review`}>Go to the review queue →</Link>
            </div>
          </Note>
        )}
      </div>
    </div>
  )
}

function OpeningBalance({ client, account, onClose, onDone }: { client: Client; account: BankAccount; onClose: () => void; onDone: () => void }) {
  const [rupees, setRupees] = useState(account.opening_balance_paise != null ? (account.opening_balance_paise / 100).toFixed(2) : '')
  const [asOf, setAsOf] = useState(account.opening_as_of ?? client.fy_start)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    // Rupees typed by a person -> whole paise, without ever holding a float
    // that has been through arithmetic: split on the decimal point instead.
    const [whole, fraction = ''] = rupees.replace(/[,\s₹]/g, '').split('.')
    const sign = whole.startsWith('-') ? -1 : 1
    const paise = sign * (Math.abs(parseInt(whole || '0', 10)) * 100 + parseInt((fraction + '00').slice(0, 2), 10))
    try {
      await api.post(`${V1}/clients/${client.id}/bank-accounts/${account.id}/opening-balance/`, {
        opening_balance_paise: paise,
        opening_as_of: asOf,
      })
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Opening balance — ${account.label}`} onClose={onClose}>
      <p className="sub">
        What the client's books actually started from, on the date they started. Pre-filled from the first statement's own opening line where one exists — confirm it rather than assume it.
      </p>
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Balance (₹)" hint="Rupees and paise, e.g. 1,23,456.78">
          <input type="text" inputMode="decimal" required value={rupees} onChange={(e) => setRupees(e.target.value)} autoFocus />
        </Field>
        <Field label="As of">
          <input type="date" required value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </Field>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Confirm
          </Button>
        </div>
      </form>
    </Modal>
  )
}
