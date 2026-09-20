// The review screen. Every row reads as a book entry -- what happened, the
// narration the voucher will carry, and which ledger it sits in and why --
// so that someone who is not an accountant can follow it, and an accountant
// can check it in a glance. Sorted by confidence, because that ordering is
// what turns an hour of checking every row into minutes of checking the ones
// that need it. Rows the system is sure of are approved in one click by
// someone who may approve; everything else is placed one at a time, and each
// placement teaches a rule that usually places several siblings.

import { useMemo, useState, type FormEvent } from 'react'
import { allPages, api, V1, waitForJob } from '../../api/client'
import type { BankAccount, Classification, Client, Job, LedgerAccount, PlacementResult, ReviewBand, ReviewSummary, Party } from '../../api/types'
import { LEDGER_GROUPS, TDS_SECTIONS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, BandBadge, Button, Empty, ErrorNote, Field, formatDate, Modal, Money, Note, Spinner, useAsync } from '../../components/ui'
import { RecategorizeButton } from './Recategorize'

type Stage = 'all' | 'unresolved' | 'pending_approval'

// What each Tally group means, in the words a client would use.
const GROUP_MEANING: Record<string, string> = {
  BANK: 'one of the client\'s own bank accounts',
  CASH: 'the cash box',
  DEBTOR: 'a customer who owes the client',
  CREDITOR: 'a supplier the client owes',
  INDIRECT_EXPENSE: 'a cost of running the business',
  DIRECT_EXPENSE: 'a cost of what the business sells',
  INDIRECT_INCOME: 'other income',
  DIRECT_INCOME: 'income from what the business sells',
  DUTIES_AND_TAXES: 'tax owed to the government',
  LOAN: 'a loan the client has taken',
  INVESTMENT: 'an investment the client holds',
  CAPITAL: 'the owner\'s own money',
  SUSPENSE: 'not yet decided',
}

// The API sends a group's display label ("Indirect Expenses"), not its code.
const GROUP_MEANING_BY_LABEL: Record<string, string> = Object.fromEntries(
  LEDGER_GROUPS.filter((g) => GROUP_MEANING[g.value]).map((g) => [g.label, GROUP_MEANING[g.value]]),
)

const VOUCHER_MEANING: Record<string, string> = {
  Payment: 'money paid out',
  Receipt: 'money received',
  Contra: 'moved between own accounts',
  Journal: 'adjustment',
}

export default function ReviewQueue({ client }: { client: Client }) {
  const { can } = useSession()
  const [band, setBand] = useState<ReviewBand | ''>('')
  const [stage, setStage] = useState<Stage>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [placing, setPlacing] = useState<Classification | null>(null)
  const [flash, setFlash] = useState<{ tone: 'good' | 'warn' | 'bad' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const summary = useAsync(() => api.get<ReviewSummary>(`${V1}/clients/${client.id}/review-queue/summary/`), [client.id])
  const queue = useAsync(() => {
    const params = new URLSearchParams()
    if (band) params.set('band', band)
    if (stage !== 'all') params.set('stage', stage)
    const qs = params.toString()
    return allPages<Classification>(`${V1}/clients/${client.id}/review-queue/${qs ? `?${qs}` : ''}`)
  }, [client.id, band, stage])
  const ledgers = useAsync(() => allPages<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`), [client.id])
  const parties = useAsync(() => allPages<Party>(`${V1}/clients/${client.id}/parties/`), [client.id])
  const accounts = useAsync(() => allPages<BankAccount>(`${V1}/clients/${client.id}/bank-accounts/`), [client.id])

  // Saying who a payee is is separate from placing the row: it teaches the
  // spelling, and every other row with that spelling is recognised at once.
  const confirmParty = async (row: Classification, partyId: string, name: string) => {
    setBusy(`who:${row.id}`)
    setError(null)
    try {
      await api.post(`${V1}/classifications/${row.id}/confirm-party/`, { party: partyId })
      setFlash({ tone: 'good', text: `Remembered: "${row.counterparty}" is ${name}. Other rows with that name are updated too.` })
      reload()
      parties.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  const reload = () => {
    summary.reload()
    queue.reload()
    setSelected(new Set())
  }

  const approvable = useMemo(() => (queue.data ?? []).filter((c) => c.ledger && !c.is_posted), [queue.data])

  async function approve(body: { classifications?: string[]; band?: ReviewBand }, label: string) {
    setBusy(label)
    setError(null)
    setFlash(null)
    try {
      const entries = await api.post<unknown[]>(`${V1}/clients/${client.id}/approvals/`, body)
      setFlash({ tone: 'good', text: `Posted ${entries.length} journal entr${entries.length === 1 ? 'y' : 'ies'}.` })
      reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  async function askModel() {
    setBusy('model')
    setError(null)
    setFlash(null)
    try {
      const started = await api.post<Job>(`${V1}/clients/${client.id}/review-queue/suggest/`)
      const job = await waitForJob(started)
      if (job.status === 'FAILED') throw new Error(job.error)
      const r = job.result as Record<string, number | string>
      if (r.error) setFlash({ tone: 'warn', text: `The model could not be reached: ${String(r.error)}. Rows stay in the queue for a person.` })
      else if (Number(r.considered) === 0) setFlash({ tone: 'info', text: 'Nothing unresolved to ask about — or no model is configured (LLM_BACKEND).' })
      else setFlash({ tone: 'info', text: `The model suggested ledgers for ${String(r.suggested)} of ${String(r.considered)} rows and declined ${String(r.declined)}.${Number(r.proposed) > 0 ? ` It proposed ${String(r.proposed)} new ledger${Number(r.proposed) === 1 ? '' : 's'}, waiting for a CA under Chart of accounts.` : ''} Every suggestion still needs a person.` })
      reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const s = summary.data

  return (
    <>
      {s && (
        <div className="grid-cards">
          <SummaryCard label="Ready to post" value={s.high} hint="booked; approve in one click" onClick={() => setBand(band === 'HIGH' ? '' : 'HIGH')} selected={band === 'HIGH'} />
          <SummaryCard label="Worth a look" value={s.advised} hint="booked; check the ledger" onClick={() => setBand(band === 'ADVISED' ? '' : 'ADVISED')} selected={band === 'ADVISED'} />
          <SummaryCard label="Needs an answer" value={s.judgement} hint="a question for the client" onClick={() => setBand(band === 'JUDGEMENT' ? '' : 'JUDGEMENT')} selected={band === 'JUDGEMENT'} />
          <SummaryCard label="Not booked yet" value={s.unresolved} hint="no ledger" onClick={() => setStage(stage === 'unresolved' ? 'all' : 'unresolved')} selected={stage === 'unresolved'} />
          <SummaryCard label="Awaiting sign-off" value={s.pending_approval} hint="booked, not yet in the ledger" onClick={() => setStage(stage === 'pending_approval' ? 'all' : 'pending_approval')} selected={stage === 'pending_approval'} />
        </div>
      )}

      <ErrorNote error={error ?? queue.error ?? summary.error} />
      {flash && <Note tone={flash.tone}>{flash.text}</Note>}

      <div className="panel">
        <div className="filter-bar">
          <span className="sub">{queue.data?.length ?? 0} rows</span>
          {(band || stage !== 'all') && (
            <Button className="btn-sm" kind="ghost" onClick={() => (setBand(''), setStage('all'))}>
              Clear filters
            </Button>
          )}
          <span className="row" />
          {can('transaction.classify') && (
            <Button className="btn-sm" onClick={() => void askModel()} busy={busy === 'model'} disabled={!!busy}>
              Ask the model about unresolved rows
            </Button>
          )}
          {can('transaction.classify') && (
            <RecategorizeButton
              client={client}
              label="Re-categorize all with AI"
              disabled={!!busy}
              onBusy={(b) => setBusy(b ? 'recat' : null)}
              onResult={(f) => {
                setFlash(f)
                reload()
              }}
            />
          )}
          {(can('journal.approve') && client.can_post) && (
            <>
              <Button className="btn-sm" kind="primary" onClick={() => void approve({ band: 'HIGH' }, 'high')} busy={busy === 'high'} disabled={!!busy || !(s?.high && approvable.some((c) => c.review_band === 'HIGH'))}>
                Approve all high-confidence
              </Button>
              <Button className="btn-sm" kind="primary" onClick={() => void approve({ classifications: [...selected] }, 'sel')} busy={busy === 'sel'} disabled={!!busy || selected.size === 0}>
                Approve {selected.size || ''} selected
              </Button>
            </>
          )}
        </div>

        <div className="legend">
          Each row is one bank line and the entry it becomes. <b>Dr · paid</b> means money left the bank; <b>Cr · received</b> means it came in.
          The ledger named is the other side of the entry — where the money went to, or came from.
        </div>
        {queue.loading ? (
          <Spinner />
        ) : !queue.data?.length ? (
          <Empty title="Nothing waiting">Every row here has been posted to the ledger, or there are no statements yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  {(can('journal.approve') && client.can_post) && <th></th>}
                  <th>Date</th>
                  <th>What the bank shows</th>
                  <th className="num">Amount</th>
                  <th>How it is booked</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {queue.data.map((c) => (
                  <tr key={c.id}>
                    {(can('journal.approve') && client.can_post) && (
                      <td>
                        <input type="checkbox" disabled={!c.ledger} checked={selected.has(c.id)} onChange={() => toggle(c.id)} aria-label="Select for approval" />
                      </td>
                    )}
                    <td>{formatDate(c.transaction.value_date)}</td>
                    <td className="narr">
                      <div className="mono">{c.transaction.narration}</div>
                      <div className="pill-row tiny">
                        {c.channel && c.channel !== 'UNKNOWN' && <Badge>{c.channel}</Badge>}
                        {c.counterparty && <span>{c.counterparty}</span>}
                        {c.is_self_transfer && <Badge tone="info">own account</Badge>}
                      </div>
                    </td>
                    <td className={`num ${c.transaction.is_debit ? 'dr' : 'cr'}`}>
                      <Money value={c.transaction.amount_display} />
                      <div className="tiny">{c.transaction.is_debit ? 'Dr · paid' : 'Cr · received'}</div>
                    </td>
                    <td className="entry">
                      {c.ledger_name ? (
                        <>
                          {c.book_narration && <div className="entry-narration">{c.book_narration}</div>}
                          <EntryLegs row={c} />
                          <div className="pill-row tiny">
                            {c.voucher_type && <Badge tone="info">{c.voucher_type} · {VOUCHER_MEANING[c.voucher_type]}</Badge>}
                            {c.ledger_opened_by_model && <Badge>new ledger</Badge>}
                            {c.party_name && <span>Party: {c.party_name}</span>}
                            {c.rcm && <Badge tone="warn">RCM</Badge>}
                            {c.tds_section && <Badge tone="info">TDS {c.tds_section}</Badge>}
                          </div>
                          {c.rationale && <div className="rationale">Why: {c.rationale}</div>}
                          {c.open_question && <div className="entry-question"><b>Ask the client:</b> {c.open_question}</div>}
                        </>
                      ) : c.open_question ? (
                        <>
                          <EntryLegs row={c} />
                          <div className="entry-question"><b>Ask the client:</b> {c.open_question}</div>
                        </>
                      ) : (
                        <>
                          <EntryLegs row={c} />
                          <span className="tiny">Not booked yet</span>
                          {c.rationale && <div className="rationale">{c.rationale}</div>}
                        </>
                      )}
                      <WhoIsThis
                        row={c}
                        canConfirm={can('transaction.classify')}
                        busy={busy === `who:${c.id}`}
                        onConfirm={(partyId, name) => confirmParty(c, partyId, name)}
                      />
                    </td>
                    <td>
                      <BandBadge band={c.review_band} />
                      <div className="tiny" title={`${Math.round(c.confidence * 100)}% sure`}>
                        {c.method === 'REVIEWED' ? 'decided by a person' : c.method === 'RULE' ? 'by a standing rule' : c.method === 'LLM' ? `by the model · ${Math.round(c.confidence * 100)}%` : ''}
                      </div>
                    </td>
                    <td className="num">
                      {can('transaction.classify') && (
                        <Button className="btn-sm" onClick={() => setPlacing(c)}>
                          {c.ledger ? 'Change' : 'Place'}
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

      {placing && (
        <PlaceRow
          client={client}
          row={placing}
          ledgers={(ledgers.data ?? []).filter((l) => l.name !== accounts.data?.find((a) => a.id === placing.transaction.bank_account)?.ledger_name)}
          parties={parties.data ?? []}
          onClose={() => setPlacing(null)}
          onDone={(result) => {
            setPlacing(null)
            setFlash({
              tone: 'good',
              text: result.also_placed > 0 ? `Placed. The rule learned from this also placed ${result.also_placed} other row${result.also_placed === 1 ? '' : 's'}.` : result.rule_learned ? 'Placed, and a rule was learned for this payee.' : 'Placed.',
            })
            ledgers.reload()
            parties.reload()
            reload()
          }}
        />
      )}
    </>
  )
}

function SummaryCard({ label, value, hint, onClick, selected }: { label: string; value: number; hint?: string; onClick: () => void; selected: boolean }) {
  return (
    <div className={`card selectable ${selected ? 'selected' : ''}`} onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onClick()}>
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {hint && <div className="tiny">{hint}</div>}
    </div>
  )
}

function PlaceRow({
  client,
  row,
  ledgers,
  parties,
  onClose,
  onDone,
}: {
  client: Client
  row: Classification
  ledgers: LedgerAccount[]
  parties: Party[]
  onClose: () => void
  onDone: (result: PlacementResult) => void
}) {
  const [ledger, setLedger] = useState(row.ledger ?? '')
  const [newLedger, setNewLedger] = useState('')
  const [newGroup, setNewGroup] = useState(row.transaction.is_debit ? 'INDIRECT_EXPENSE' : 'INDIRECT_INCOME')
  const [party, setParty] = useState(row.party ?? '')
  const [newParty, setNewParty] = useState('')
  const [rcm, setRcm] = useState(row.rcm)
  const [tds, setTds] = useState(row.tds_section)
  const [learn, setLearn] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      let ledgerId = ledger
      if (ledger === '__new__') {
        const created = await api.post<LedgerAccount>(`${V1}/clients/${client.id}/ledgers/`, { name: newLedger.trim(), group: newGroup })
        ledgerId = created.id
      }
      let partyId: string | null = party || null
      if (party === '__new__') {
        const created = await api.post<Party>(`${V1}/clients/${client.id}/parties/`, { canonical_name: newParty.trim(), rcm_default: rcm, tds_section: tds })
        partyId = created.id
      }
      const result = await api.post<PlacementResult>(`${V1}/classifications/${row.id}/review/`, {
        ledger: ledgerId,
        party: partyId,
        rcm,
        tds_section: tds,
        learn,
      })
      onDone(result)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const activeLedgers = ledgers.filter((l) => l.is_active && l.status === 'ACTIVE')
  const grouped = LEDGER_GROUPS.map((g) => ({ ...g, items: activeLedgers.filter((l) => l.group === g.value) })).filter((g) => g.items.length)

  return (
    <Modal title="Place this transaction" onClose={onClose}>
      <div className="kv">
        <dt>Date</dt>
        <dd>{formatDate(row.transaction.value_date)}</dd>
        <dt>Amount</dt>
        <dd className={row.transaction.is_debit ? 'dr' : 'cr'}>
          <Money value={row.transaction.amount_display} /> {row.transaction.is_debit ? '(paid out)' : '(received)'}
        </dd>
        <dt>Narration</dt>
        <dd className="mono">{row.transaction.narration}</dd>
        {row.counterparty && (
          <>
            <dt>Counterparty</dt>
            <dd>{row.counterparty}</dd>
          </>
        )}
        {row.rationale && (
          <>
            <dt>Model said</dt>
            <dd className="rationale">“{row.rationale}”</dd>
          </>
        )}
      </div>
      <hr className="sep" />
      <form onSubmit={submit}>
        <ErrorNote error={error} />
        <Field label="Ledger head" hint="Must match the ledger name in the client's Tally company exactly.">
          <select required value={ledger} onChange={(e) => setLedger(e.target.value)} autoFocus>
            <option value="">— choose —</option>
            {grouped.map((g) => (
              <optgroup key={g.value} label={g.label}>
                {g.items.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value="__new__">+ New ledger…</option>
          </select>
        </Field>
        {ledger === '__new__' && (
          <div className="inline-form">
            <Field label="New ledger name">
              <input type="text" required value={newLedger} onChange={(e) => setNewLedger(e.target.value)} />
            </Field>
            <Field label="Group">
              <select value={newGroup} onChange={(e) => setNewGroup(e.target.value)}>
                {LEDGER_GROUPS.map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
        <Field label="Party (party)" hint="Who it was with, where there is an identifiable one. Optional.">
          <select value={party} onChange={(e) => setParty(e.target.value)}>
            <option value="">— none —</option>
            {parties
              .filter((v) => v.is_active)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.canonical_name}
                </option>
              ))}
            <option value="__new__">+ New party…</option>
          </select>
        </Field>
        {party === '__new__' && (
          <Field label="New party name">
            <input type="text" required value={newParty || row.counterparty} onChange={(e) => setNewParty(e.target.value)} />
          </Field>
        )}
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
            Reverse charge applies (client pays the GST)
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} />
          Learn a rule for this payee, so it is placed automatically from now on
        </label>
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={busy}>
            Place
          </Button>
        </div>
      </form>
    </Modal>
  )
}

// Who the payee is, as far as the system can tell. A recognised payee is a fact
// (an exact name, or a spelling someone confirmed); a "could be" is only a
// suggestion, so it comes with its reason and needs a person to say yes.
function WhoIsThis({ row, canConfirm, busy, onConfirm }: {
  row: Classification
  canConfirm: boolean
  busy: boolean
  onConfirm: (partyId: string, name: string) => void
}) {
  if (!row.counterparty || row.is_self_transfer) return null

  if (row.party_resolution === 'CANDIDATE' && row.party_candidates.length > 0) {
    return (
      <div className="payee">
        <div className="tiny"><b>Is this someone you know?</b></div>
        {row.party_candidates.map((c) => (
          <div key={c.party} className="payee-candidate">
            <span><strong>{c.name}</strong> <span className="tiny">— {c.why}</span></span>
            {canConfirm && (
              <Button className="btn-sm" busy={busy} onClick={() => onConfirm(c.party, c.name)}>
                Yes, same
              </Button>
            )}
          </div>
        ))}
      </div>
    )
  }

  // A placed row already shows its party beside the ledger.
  if (row.ledger_name) return null

  if ((row.party_resolution === 'AUTO' || row.party_resolution === 'CONFIRMED') && row.party_name) {
    return (
      <div className="pill-row tiny">
        <Badge tone="good">{row.party_resolution === 'CONFIRMED' ? 'confirmed' : 'recognised'}</Badge>
        <span>{row.party_name}</span>
      </div>
    )
  }
  return <div className="tiny">New payee, not a known party yet</div>
}

// The entry as a voucher shows it: two lines, one debit and one credit, for the
// same amount. Every transaction has two sides, and showing only the one the
// reviewer is choosing hides the other and makes the entry look half-made.
function EntryLegs({ row }: { row: Classification }) {
  return (
    <table className="legs" aria-label="Entry">
      <tbody>
        {row.entry_legs.map((leg) => (
          <tr key={leg.side}>
            <td className="leg-side">{leg.side}</td>
            <td className={leg.ledger ? '' : 'leg-missing'}>
              {leg.ledger ?? 'ledger not chosen'}
              {!leg.is_bank && leg.group && GROUP_MEANING_BY_LABEL[leg.group] && (
                <span className="tiny"> — {GROUP_MEANING_BY_LABEL[leg.group]}</span>
              )}
            </td>
            <td className="num"><Money value={leg.amount_display} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
