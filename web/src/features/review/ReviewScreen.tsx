// Deciding where each bank transaction goes, then posting it.
//
// Two stages, kept visibly apart because the server keeps them apart: a row is first PLACED
// in a ledger (by a rule, the assistant, or you), and then POSTED, which writes the journal
// entry. "Needs a ledger" is the work; "Ready to post" is the check before it enters the
// books. The queue is on the left, the decision on the right, and the keyboard moves through
// it as fast as a CA reads: J/K to move, L for the ledger, Enter to place, P to post.

import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, Bot, CheckCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { waitForJob } from '@/api/jobs'
import { ledgers as ledgersQuery, parties as partiesQuery, reviewQueue, type Stage } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary, useInvalidateClient, V1 } from '@/api/queries/clients'
import { TDS_SECTIONS, type Classification, type Job, type JournalEntry, type PlacementResult } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox, Select } from '@/components/ui/controls'
import { Kbd } from '@/components/ui/kbd'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { LedgerPicker, usableLedgers } from './LedgerPicker'

const STAGES: { stage: Stage; label: string; hint: string }[] = [
  { stage: 'unresolved', label: 'Needs a ledger', hint: 'No ledger yet. Decide where each one goes.' },
  { stage: 'pending_approval', label: 'Ready to post', hint: 'Placed in a ledger, not yet in the books. Check and post.' },
  { stage: 'all', label: 'All waiting', hint: 'Everything not yet posted.' },
]

const BAND_LABEL: Record<string, { label: string; tone: 'success' | 'info' | 'warning' }> = {
  HIGH: { label: 'High', tone: 'success' },
  ADVISED: { label: 'Check', tone: 'info' },
  JUDGEMENT: { label: 'Decide', tone: 'warning' },
}

export function ReviewScreen({ clientId, stage: asked }: { clientId: string; stage?: Stage }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const summary = useQuery(reviewSummary(clientId))
  // Opened without saying which stage: go where the work is.
  const stage: Stage = asked ?? (!summary.data?.unresolved && summary.data?.pending_approval ? 'pending_approval' : 'unresolved')
  const queue = useQuery(reviewQueue(clientId, stage))
  const ledgers = useQuery(ledgersQuery(clientId))
  const accounts = useQuery(bankAccounts(clientId))
  const invalidate = useInvalidateClient(clientId)

  const [band, setBand] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [confirmHigh, setConfirmHigh] = useState(false)
  const [confirmTicked, setConfirmTicked] = useState(false)

  const rows = useMemo(
    () => (queue.data ?? []).filter((r) => !band || r.review_band === band),
    [queue.data, band],
  )
  const index = Math.max(0, rows.findIndex((r) => r.id === selectedId))
  const selected = rows[index] ?? null
  // Keep a row selected: the first one on arrival, and the one now in the same place after a row leaves.
  useEffect(() => {
    if (rows.length && !rows.some((r) => r.id === selectedId)) setSelectedId(rows[Math.min(index, rows.length - 1)]!.id)
  }, [rows, selectedId, index])
  useEffect(() => setTicked(new Set()), [stage, band])

  const canPost = can('journal.approve') && !!client.data?.can_post
  const postable = (r: Classification) => !!r.ledger && !r.is_posted
  const tickedRows = rows.filter((r) => ticked.has(r.id) && postable(r))
  const proposed = (ledgers.data ?? []).filter((l) => l.status === 'PROPOSED')

  const suggest = useMutation({
    mutationFn: async () => waitForJob(await raw.post<Job>(`${V1}/clients/${clientId}/review-queue/suggest/`)),
    onSuccess: async (job) => {
      await invalidate()
      const r = job.result as { suggested?: number; declined?: number; proposed?: number; error?: string }
      if (r?.error) toast.warning(job.message || `The assistant stopped before it finished: ${r.error}`)
      else
        toast.success(`The assistant suggested ledgers for ${plural(r?.suggested ?? 0, 'row')}`, {
          description: [r?.declined ? `${r.declined} it was unsure about` : '', r?.proposed ? `${plural(r.proposed, 'new ledger')} proposed` : '']
            .filter(Boolean)
            .join(' · '),
        })
    },
    onError: (e) => toast.error(messageOf(e)),
  })

  async function post(body: { classifications: string[] } | { band: 'HIGH' }) {
    const entries = await raw.post<JournalEntry[]>(`${V1}/clients/${clientId}/approvals/`, body)
    await invalidate()
    setTicked(new Set())
    toast.success(`Posted ${plural(entries.length, 'entry', 'entries')} to the Day Book`)
  }

  function move(delta: number) {
    const next = rows[Math.min(Math.max(index + delta, 0), rows.length - 1)]
    if (next) {
      setSelectedId(next.id)
      document.getElementById(`row-${next.id}`)?.scrollIntoView({ block: 'nearest' })
    }
  }
  useHotkey('j', 'Next row', () => move(1), 'Review')
  useHotkey('arrowdown', 'Next row', () => move(1), 'Review')
  useHotkey('k', 'Previous row', () => move(-1), 'Review')
  useHotkey('arrowup', 'Previous row', () => move(-1), 'Review')
  useHotkey('x', 'Tick the row for posting', () => {
    if (!selected) return
    setTicked((t) => {
      const next = new Set(t)
      if (next.has(selected.id)) next.delete(selected.id)
      else next.add(selected.id)
      return next
    })
  }, 'Review')

  const highCount = summary.data?.bulk_approvable ?? 0
  const bankLedgerOf = (row: Classification) => accounts.data?.results.find((a) => a.id === row.transaction.bank_account)?.ledger_name

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Review stage" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
          {STAGES.map((s) => {
            const count =
              s.stage === 'unresolved' ? summary.data?.unresolved : s.stage === 'pending_approval' ? summary.data?.pending_approval : summary.data?.total
            return (
              <Link
                key={s.stage}
                to="/clients/$clientId/review"
                params={{ clientId }}
                search={{ stage: s.stage }}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground',
                  stage === s.stage && 'bg-card text-foreground shadow-xs',
                )}
              >
                {s.label} <span className="num ml-1 text-xs">{count ?? '…'}</span>
              </Link>
            )
          })}
        </nav>
        <div className="flex flex-wrap gap-2">
          {can('transaction.classify') && (
            <Button variant="outline" onClick={() => suggest.mutate()} disabled={suggest.isPending || !summary.data?.unresolved}>
              <Sparkles /> {suggest.isPending ? 'Asking the assistant…' : 'Ask assistant to suggest'}
            </Button>
          )}
          {canPost && tickedRows.length > 0 && (
            <Button onClick={() => setConfirmTicked(true)}>
              <CheckCheck /> Post {tickedRows.length} ticked
            </Button>
          )}
          {canPost && highCount > 0 && (
            <Button variant={tickedRows.length ? 'outline' : 'primary'} onClick={() => setConfirmHigh(true)}>
              <CheckCheck /> Post all high-confidence ({highCount})
            </Button>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground">{STAGES.find((s) => s.stage === stage)?.hint}</p>

      {proposed.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-info/40 bg-info/8 px-4 py-2.5 text-sm">
          <span>
            <Bot className="mr-1.5 inline size-4 text-info" aria-hidden />
            The assistant has proposed {plural(proposed.length, 'new ledger')} ({proposed.slice(0, 3).map((l) => l.name).join(', ')}
            {proposed.length > 3 ? '…' : ''}). Rows can go in them once a senior CA accepts them.
          </span>
          <Button asChild size="sm" variant="outline">
            <Link to="/clients/$clientId/masters" params={{ clientId }} search={{ tab: 'ledgers' }}>
              Review proposals
            </Link>
          </Button>
        </div>
      )}

      {stage !== 'unresolved' && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Confidence:</span>
          {['', 'HIGH', 'ADVISED', 'JUDGEMENT'].map((b) => (
            <button
              key={b || 'any'}
              type="button"
              onClick={() => setBand(b)}
              className={cn('rounded-full border px-2.5 py-0.5', band === b ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-hover')}
            >
              {b ? BAND_LABEL[b]!.label : 'Any'}
            </button>
          ))}
        </div>
      )}

      {queue.isPending ? (
        <Spinner label="Loading the queue…" />
      ) : queue.error ? (
        <ErrorState error={queue.error} retry={() => void queue.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={stage === 'unresolved' ? 'Every transaction has a ledger' : 'Nothing is waiting here'}>
          {stage === 'unresolved' && (summary.data?.pending_approval ?? 0) > 0 ? (
            <>
              {plural(summary.data!.pending_approval, 'row')} placed and ready to post.{' '}
              <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'pending_approval' }} className="underline">
                Go to Ready to post
              </Link>
              .
            </>
          ) : (summary.data?.total ?? 0) === 0 ? (
            'Everything uploaded is posted. Upload the next statement, or read the reports.'
          ) : null}
        </EmptyState>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(360px,1fr)]">
          <Card className="max-h-[70vh] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 border-b bg-muted text-[13px] text-muted-foreground">
                <tr>
                  {canPost && stage !== 'unresolved' && (
                    <th className="w-8 px-3 py-2">
                      <Checkbox
                        aria-label="Tick every row that can be posted"
                        checked={rows.filter(postable).length > 0 && rows.filter(postable).every((r) => ticked.has(r.id))}
                        onChange={(e) => setTicked(e.target.checked ? new Set(rows.filter(postable).map((r) => r.id)) : new Set())}
                      />
                    </th>
                  )}
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 font-medium">Narration</th>
                  <th className="px-3 py-2 text-right font-medium">Withdrawal</th>
                  <th className="px-3 py-2 text-right font-medium">Deposit</th>
                  <th className="px-3 py-2 font-medium">Ledger</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    id={`row-${r.id}`}
                    onClick={() => setSelectedId(r.id)}
                    aria-selected={r.id === selected?.id}
                    className={cn('h-(--row-h) cursor-pointer border-b', r.id === selected?.id ? 'bg-accent/15' : 'hover:bg-hover')}
                  >
                    {canPost && stage !== 'unresolved' && (
                      <td className="px-3" onClick={(e) => e.stopPropagation()}>
                        {postable(r) && (
                          <Checkbox
                            aria-label="Tick for posting"
                            checked={ticked.has(r.id)}
                            onChange={(e) =>
                              setTicked((t) => {
                                const n = new Set(t)
                                if (e.target.checked) n.add(r.id)
                                else n.delete(r.id)
                                return n
                              })
                            }
                          />
                        )}
                      </td>
                    )}
                    <td className="num whitespace-nowrap px-3">{formatDate(r.transaction.value_date)}</td>
                    <td className="max-w-52 truncate px-3" title={r.transaction.narration}>
                      {r.counterparty || r.transaction.narration}
                    </td>
                    <td className="num whitespace-nowrap px-3 text-right">{r.transaction.is_debit ? r.transaction.amount_display : ''}</td>
                    <td className="num whitespace-nowrap px-3 text-right">{!r.transaction.is_debit ? r.transaction.amount_display : ''}</td>
                    <td className="max-w-44 px-3">
                      {r.ledger_name ? (
                        <span className="flex items-center gap-1.5">
                          <span className="truncate">{r.ledger_name}</span>
                          {BAND_LABEL[r.review_band] && r.method !== 'REVIEWED' && (
                            <Badge tone={BAND_LABEL[r.review_band]!.tone}>{BAND_LABEL[r.review_band]!.label}</Badge>
                          )}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {selected && (
            <Decision
              key={selected.id}
              clientId={clientId}
              row={selected}
              ledgers={usableLedgers(ledgers.data, bankLedgerOf(selected))}
              canPost={canPost}
              onDone={() => move(0)}
            />
          )}
        </div>
      )}

      <Confirm
        open={confirmHigh}
        onOpenChange={setConfirmHigh}
        title={`Post ${plural(highCount, 'high-confidence row')}?`}
        confirmLabel={`Post ${highCount}`}
        onConfirm={() => post({ band: 'HIGH' })}
      >
        <p>
          These were placed by the client’s rules with high confidence. Each becomes a journal entry in the Day Book. Until the books are
          signed off you can still correct or remove any of them.
        </p>
      </Confirm>
      <Confirm
        open={confirmTicked}
        onOpenChange={setConfirmTicked}
        title={`Post ${plural(tickedRows.length, 'ticked row')}?`}
        confirmLabel={`Post ${tickedRows.length}`}
        onConfirm={() => post({ classifications: tickedRows.map((r) => r.id) })}
      >
        <p>Each becomes a journal entry in the Day Book, in the ledger shown. All are posted together, or none.</p>
      </Confirm>
    </div>
  )
}

/** Everything needed to decide one row, and the two actions: place it, and post it. */
function Decision({
  clientId,
  row,
  ledgers,
  canPost,
  onDone,
}: {
  clientId: string
  row: Classification
  ledgers: ReturnType<typeof usableLedgers>
  canPost: boolean
  onDone: () => void
}) {
  const { can } = useSession()
  const parties = useQuery(partiesQuery(clientId))
  const invalidate = useInvalidateClient(clientId)
  const ledgerInput = useRef<HTMLInputElement>(null)
  const suggested = ledgers.some((l) => l.id === row.ledger) ? row.ledger : null
  const [ledger, setLedger] = useState<string | null>(suggested)
  const [party, setParty] = useState<string>(row.party ?? '')
  const [tds, setTds] = useState<string>(row.tds_section ?? '')
  const [rcm, setRcm] = useState(row.rcm)
  const [learn, setLearn] = useState(!row.is_self_transfer && !!row.counterparty)
  const [busy, setBusy] = useState(false)
  const t = row.transaction
  const canPlace = can('transaction.classify')
  const unchanged = ledger === row.ledger && (party || null) === (row.party ?? null) && tds === (row.tds_section ?? '') && rcm === row.rcm
  const alreadyPlacedByPerson = row.method === 'REVIEWED' && unchanged

  async function place() {
    if (!ledger) return ledgerInput.current?.focus()
    setBusy(true)
    try {
      const result = await raw.post<PlacementResult>(`${V1}/classifications/${row.id}/review/`, {
        ledger,
        party: party || null,
        rcm,
        tds_section: tds,
        learn,
      })
      await invalidate()
      const extra = [
        learn && result.rule_learned ? `Remembered for ${row.counterparty}` : '',
        learn && !result.rule_learned ? 'Nothing was remembered: no payee could be read' : '',
        result.also_placed ? `${plural(result.also_placed, 'other row')} from the same payee placed too` : '',
        result.auto_posted ? `${result.auto_posted} posted automatically` : '',
      ].filter(Boolean)
      toast.success(`Placed in ${result.classification.ledger_name}`, { description: extra.join(' · ') || undefined })
      onDone()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  async function postNow() {
    setBusy(true)
    try {
      await raw.post(`${V1}/clients/${clientId}/approvals/`, { classifications: [row.id] })
      await invalidate()
      toast.success('Posted to the Day Book')
      onDone()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  async function confirmParty(id: string) {
    try {
      await raw.post(`${V1}/classifications/${row.id}/confirm-party/`, { party: id })
      await invalidate()
      setParty(id)
      toast.success('Payee confirmed', { description: 'Every other waiting row with this spelling is now recognised too.' })
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  useHotkey('l', 'Choose the ledger', () => ledgerInput.current?.focus(), 'Review')
  useHotkey('enter', 'Place the row in the chosen ledger', () => canPlace && !busy && !alreadyPlacedByPerson && void place(), 'Review')
  useHotkey('p', 'Post this row', () => canPost && row.ledger && unchanged && !busy && void postNow(), 'Review')

  // The entry as it will be posted with what is chosen now, not as it was suggested.
  const chosenLedger = ledgers.find((l) => l.id === ledger)
  const chosenParty = parties.data?.find((p) => p.id === party)
  const legs = (row.entry_legs ?? []).map((leg) => (leg.is_bank ? leg : { ...leg, ledger: chosenLedger?.name ?? null }))
  const extras = [chosenParty?.canonical_name, tds && `TDS ${tds}`, rcm && 'Reverse charge'].filter(Boolean).join(' · ')
  return (
    <Card className="grid content-start gap-4 p-4 xl:sticky xl:top-20">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="num text-sm text-muted-foreground">{formatDate(t.value_date)}</span>
          <span className={cn('num text-lg font-semibold', t.is_debit ? 'text-foreground' : 'text-success')}>
            {t.is_debit ? 'Paid ' : 'Received '}
            {t.amount_display}
          </span>
        </div>
        <p className="mt-1 break-words font-mono text-[13px]">{t.narration}</p>
        <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
          {row.channel && row.channel !== 'UNKNOWN' && <Badge>{row.channel}</Badge>}
          {row.counterparty && <Badge tone="outline">{row.counterparty}</Badge>}
          {row.is_self_transfer && <Badge tone="info">Between the client’s own accounts</Badge>}
        </div>
      </div>

      {row.open_question && (
        <div className="flex gap-2 rounded-md border border-warning/50 bg-warning/10 p-2.5 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>{row.open_question}</span>
        </div>
      )}

      {legs.length > 0 && (
        <div>
          <div className="mb-1 text-[13px] font-medium">The entry this makes</div>
          <table className="w-full text-sm">
            <tbody>
              {legs.map((leg, i) => (
                <tr key={i} className="border-b last:border-b-0">
                  <td className="w-8 py-1 text-muted-foreground">{leg.side}</td>
                  <td className="py-1">{leg.ledger ?? <span className="italic text-muted-foreground">choose a ledger</span>}</td>
                  <td className="num py-1 text-right">
                    <Money display={leg.amount_display} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {extras && <p className="mt-1 text-xs text-muted-foreground">{extras}</p>}
          {ledger !== row.ledger && ledger && <p className="mt-1 text-xs text-info">Not saved yet: press Enter or Place in ledger.</p>}
        </div>
      )}

      {row.ledger && row.method !== 'REVIEWED' && (
        <div className="text-[13px] text-muted-foreground">
          <span className="font-medium text-foreground">{row.method_display}</span>
          {row.confidence ? ` · ${Math.round(row.confidence * 100)}% sure` : ''}
          {row.rationale && <p className="mt-0.5">{row.rationale}</p>}
        </div>
      )}

      {canPlace ? (
        <div className="grid gap-3">
          <LedgerPicker
            clientId={clientId}
            ledgers={ledgers}
            value={ledger}
            onChange={setLedger}
            inputRef={ledgerInput}
            label="Ledger (the other side of the entry)"
            suggestedGroup={t.is_debit ? 'INDIRECT_EXPENSE' : 'INDIRECT_INCOME'}
          />

          <div className="grid gap-1.5">
            <label className="text-[13px] font-medium" htmlFor={`party-${row.id}`}>
              Party (who it was paid to or received from)
            </label>
            {row.party_candidates?.length > 0 && !row.party && (
              <div className="flex flex-wrap gap-1.5">
                {row.party_candidates.slice(0, 3).map((c) => (
                  <Button key={c.party} size="sm" variant="outline" onClick={() => void confirmParty(c.party)} title={c.why}>
                    Is it {c.name}?
                  </Button>
                ))}
              </div>
            )}
            <Select id={`party-${row.id}`} value={party} onChange={(e) => setParty(e.target.value)}>
              <option value="">No party</option>
              {(parties.data ?? [])
                .filter((p) => p.is_active !== false)
                .map((p) => (
                  <option key={p.id} value={p.id}>{p.canonical_name}</option>
                ))}
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <label className="text-[13px] font-medium" htmlFor={`tds-${row.id}`}>TDS section</label>
              <Select id={`tds-${row.id}`} value={tds} onChange={(e) => setTds(e.target.value)}>
                {TDS_SECTIONS.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </Select>
            </div>
            <div className="flex items-end pb-2">
              <Checkbox label="Reverse charge (RCM)" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
            </div>
          </div>

          {row.counterparty && !row.is_self_transfer ? (
            <Checkbox
              label={`Remember this for every payment ${t.is_debit ? 'to' : 'from'} ${row.counterparty}`}
              checked={learn}
              onChange={(e) => setLearn(e.target.checked)}
            />
          ) : (
            <p className="text-xs text-muted-foreground">
              {row.is_self_transfer
                ? 'A transfer between the client’s own accounts is decided each time, so nothing is remembered.'
                : 'The payee could not be read from this narration, so this decision applies to this row only. Add a rule in Masters if it repeats.'}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            {!alreadyPlacedByPerson && (
              <Button variant={row.ledger && unchanged ? 'outline' : 'primary'} onClick={() => void place()} disabled={busy || !ledger}>
                {row.ledger && ledger === row.ledger ? 'Confirm ledger' : 'Place in ledger'} <Kbd className="ml-1 bg-transparent">Enter</Kbd>
              </Button>
            )}
            {canPost && row.ledger && unchanged && (
              <Button onClick={() => void postNow()} disabled={busy}>
                Post entry <Kbd className="ml-1 bg-transparent text-primary-foreground/80">P</Kbd>
              </Button>
            )}
          </div>
          {canPost && row.ledger && !unchanged && (
            <p className="text-right text-xs text-muted-foreground">Place it with your changes first, then post.</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Your role can look at the queue but not place rows.</p>
      )}
    </Card>
  )
}
