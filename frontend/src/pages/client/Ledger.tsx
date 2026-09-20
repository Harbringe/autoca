// The permanent record. Read-only, except for corrections -- which are new
// entries pointing at the old one. The original stays, struck through, with
// the chain visible.

import { useState, type FormEvent } from 'react'
import { allPages, api, V1 } from '../../api/client'
import type { Client, JournalEntry, LedgerAccount, Party } from '../../api/types'
import { TDS_SECTIONS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, formatDate, formatDateTime, Modal, Money, Spinner, useAsync } from '../../components/ui'

export default function Ledger({ client }: { client: Client }) {
  const { can } = useSession()
  const [liveOnly, setLiveOnly] = useState(false)
  const [correcting, setCorrecting] = useState<JournalEntry | null>(null)
  const entries = useAsync(() => allPages<JournalEntry>(`${V1}/journal-entries/?client=${client.id}${liveOnly ? '&live=true' : ''}`), [client.id, liveOnly])
  const ledgers = useAsync(() => allPages<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`), [client.id])
  const parties = useAsync(() => allPages<Party>(`${V1}/clients/${client.id}/parties/`), [client.id])

  return (
    <>
      <div className="panel">
        <div className="filter-bar">
          <span className="sub">{entries.data?.length ?? 0} entries</span>
          <label className="check">
            <input type="checkbox" checked={liveOnly} onChange={(e) => setLiveOnly(e.target.checked)} />
            Hide corrected entries
          </label>
        </div>
        <ErrorNote error={entries.error} />
        {entries.loading ? (
          <Spinner />
        ) : !entries.data?.length ? (
          <Empty title="Nothing posted yet">Entries appear here when a senior CA approves rows from the review queue.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Voucher</th>
                  <th>Date</th>
                  <th>Narration</th>
                  <th>Lines</th>
                  <th className="num">Amount</th>
                  <th>Approved</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {entries.data.map((entry) => (
                  <tr key={entry.id} className={entry.is_superseded ? 'superseded' : ''}>
                    <td>
                      <strong>
                        {entry.voucher_type} {entry.entry_no}
                      </strong>
                      <div className="tiny">FY {entry.fy_label}</div>
                      {entry.is_superseded && (
                        <div className="no-strike">
                          <Badge tone="warn">Corrected</Badge>
                        </div>
                      )}
                      {entry.supersedes && (
                        <div className="no-strike">
                          <Badge tone="info">Correction</Badge>
                        </div>
                      )}
                    </td>
                    <td>{formatDate(entry.entry_date)}</td>
                    <td className="narr mono">{entry.narration}</td>
                    <td>
                      {entry.lines.map((line) => (
                        <div key={line.id} className="tiny">
                          <span className={line.direction === 'DR' ? 'dr' : 'cr'}>{line.direction}</span> {line.ledger_name}
                          {line.party_name ? ` · ${line.party_name}` : ''} <Money value={line.amount_display} muted />
                          {line.rcm ? ' · RCM' : ''}
                          {line.tds_section ? ` · TDS ${line.tds_section}` : ''}
                        </div>
                      ))}
                    </td>
                    <td className="num">
                      <Money value={entry.total_display} />
                    </td>
                    <td className="tiny">
                      {entry.approved_by_email}
                      <div>{formatDateTime(entry.approved_at)}</div>
                    </td>
                    <td className="num">
                      {can('journal.correct') && client.can_post && !entry.is_superseded && entry.source_transaction && (
                        <Button className="btn-sm" onClick={() => setCorrecting(entry)}>
                          Correct
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

      {correcting && (
        <Correct
          entry={correcting}
          ledgers={ledgers.data ?? []}
          parties={parties.data ?? []}
          onClose={() => setCorrecting(null)}
          onDone={() => {
            setCorrecting(null)
            entries.reload()
          }}
        />
      )}
    </>
  )
}

function Correct({ entry, ledgers, parties, onClose, onDone }: { entry: JournalEntry; ledgers: LedgerAccount[]; parties: Party[]; onClose: () => void; onDone: () => void }) {
  const other = entry.lines.find((l) => !ledgers.find((x) => x.id === l.ledger_account)?.is_bank_or_cash) ?? entry.lines[0]
  const [ledger, setLedger] = useState(other?.ledger_account ?? '')
  const [party, setParty] = useState(other?.party ?? '')
  const [rcm, setRcm] = useState(other?.rcm ?? false)
  const [tds, setTds] = useState(other?.tds_section ?? '')
  const [narration, setNarration] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`${V1}/journal-entries/${entry.id}/correct/`, {
        treatment: { ledger, party: party || null, rcm, tds_section: tds, learn: true },
        narration: narration || undefined,
      })
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Correct ${entry.voucher_type} ${entry.entry_no}`} onClose={onClose}>
      <p className="sub">
        The original is not edited — it cannot be. A new entry will reverse its lines and post the corrected treatment, linked back to it. Both stay in the record.
      </p>
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Corrected ledger head">
          <select required value={ledger} onChange={(e) => setLedger(e.target.value)} autoFocus>
            <option value="">— choose —</option>
            {ledgers
              .filter((l) => l.is_active && l.status === 'ACTIVE')
              .map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Party">
          <select value={party} onChange={(e) => setParty(e.target.value)}>
            <option value="">— none —</option>
            {parties.map((v) => (
              <option key={v.id} value={v.id}>
                {v.canonical_name}
              </option>
            ))}
          </select>
        </Field>
        <div className="inline-form">
          <Field label="TDS section">
            <select value={tds} onChange={(e) => setTds(e.target.value)}>
              {TDS_SECTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <label className="check">
            <input type="checkbox" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
            Reverse charge
          </label>
        </div>
        <Field label="Narration for the correcting entry" hint="Defaults to the original's.">
          <input type="text" value={narration} onChange={(e) => setNarration(e.target.value)} />
        </Field>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Post correction
          </Button>
        </div>
      </form>
    </Modal>
  )
}
