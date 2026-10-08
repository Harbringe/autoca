// Deciding where each bank transaction goes, then posting it.
//
// Two stages, kept visibly apart because the server keeps them apart: a row is first PLACED
// in a ledger (by a rule, the assistant, or you), and then POSTED, which writes the journal
// entry. "Needs a ledger" is the work; "Ready to post" is the check before it enters the
// books. The queue is on the left, the decision on the right, and the keyboard moves through
// it as fast as a CA reads: J/K to move, L for the ledger, Enter to place, P to post.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, Bot, CheckCheck, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { waitForJob } from '@/api/jobs'
import { ledgers as ledgersQuery, parties as partiesQuery, reviewQueue, rules as rulesQuery, type ReviewTab, type Stage } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary, useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, TDS_SECTIONS, type Classification, type Job, type JournalEntry, type PlacementResult } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { AssistantStrip } from '@/features/assistant/AssistantStrip'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { Checkbox, Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Kbd } from '@/components/ui/kbd'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatPaise, plainAmount, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { summariseBulk, type BulkSummary } from './bulkPost'
import { SettlementPanel } from './SettlementPanel'
import { LedgerPicker, usableLedgers } from './LedgerPicker'
import { ProposalDecision } from '@/features/masters/MastersScreen'
import { PostedEntries } from './PostedEntries'
import { StageNav, STAGES } from './StageNav'


const BAND_LABEL: Record<string, { label: string; tone: 'success' | 'info' | 'warning' }> = {
  HIGH: { label: 'High', tone: 'success' },
  ADVISED: { label: 'Check', tone: 'info' },
  JUDGEMENT: { label: 'Decide', tone: 'warning' },
}

// A small coloured dot says how sure the assistant is; nothing at all means high confidence.
const DOT: Record<string, { className: string; word: string; title: string }> = {
  ADVISED: { className: 'bg-accent-foreground', word: 'Check', title: 'Check: the assistant is fairly sure, but a person should look' },
  JUDGEMENT: { className: 'bg-destructive', word: 'Decide', title: 'Decide: the assistant is unsure, this needs your judgement' },
}

type SortKey = 'date' | 'amount'
type Sort = { key: SortKey; dir: 'asc' | 'desc' } | null

/** What a row is called to a screen reader, so "select" says which row. */
function rowName(r: Classification): string {
  const narration = r.counterparty || r.transaction.narration
  return `${formatDate(r.transaction.value_date)} ${r.transaction.amount_display} ${narration.length > 60 ? `${narration.slice(0, 60)}…` : narration}`
}

/** The review screen: the queues of waiting rows, or Posted, which lists the entries already in the books. */
export function ReviewScreen({ clientId, stage }: { clientId: string; stage?: ReviewTab }) {
  if (stage === 'posted') return <PostedEntries clientId={clientId} />
  return <ReviewQueue clientId={clientId} stage={stage} />
}

function ReviewQueue({ clientId, stage: asked }: { clientId: string; stage?: Stage }) {
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
  // Frozen when the dialog opens: the live count drops to 0 the moment the posting succeeds.
  const [bulk, setBulk] = useState<{ count: number; summary: BulkSummary | null }>({ count: 0, summary: null })
  const [confirmTicked, setConfirmTicked] = useState(false)
  const [text, setText] = useState('')
  const [sort, setSort] = useState<Sort>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const phone = useMediaQuery('(max-width: 639px)')
  const [sheet, setSheet] = useState(false)

  const rows = useMemo(() => {
    const q = text.trim().toLowerCase()
    const qa = plainAmount(q)
    const kept = (queue.data ?? [])
      .filter((r) => !band || r.review_band === band)
      .filter(
        (r) =>
          !q ||
          r.transaction.narration.toLowerCase().includes(q) ||
          (r.counterparty ?? '').toLowerCase().includes(q) ||
          (r.ledger_name ?? '').toLowerCase().includes(q) ||
          (qa !== '' && plainAmount(r.transaction.amount_display ?? '').includes(qa)),
      )
    if (!sort) return kept
    const sign = sort.dir === 'asc' ? 1 : -1
    // Array.sort is stable, so equal dates or amounts keep the order the statement had.
    return [...kept].sort((a, b) =>
      sort.key === 'date'
        ? sign * a.transaction.value_date.localeCompare(b.transaction.value_date)
        : sign * (a.transaction.amount_paise - b.transaction.amount_paise),
    )
  }, [queue.data, band, text, sort])
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s?.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null))
  const index = Math.max(0, rows.findIndex((r) => r.id === selectedId))
  const selected = rows[index] ?? null
  // Keep a row selected: the first one on arrival, and the one now in the same place after a row leaves.
  useEffect(() => {
    if (rows.length && !rows.some((r) => r.id === selectedId)) setSelectedId(rows[Math.min(index, rows.length - 1)]!.id)
  }, [rows, selectedId, index])
  useEffect(() => setTicked(new Set()), [stage, band])

  const canPost = can('journal.approve') && !!client.data?.can_post
  // A row on a party's account is never ticked or posted in bulk: a person says which bills it settles, one row at a time.
  const postable = (r: Classification) => !!r.ledger && !r.is_posted && !r.on_party_account
  const tickedRows = rows.filter((r) => ticked.has(r.id) && postable(r))
  const proposed = (ledgers.data ?? []).filter((l) => l.status === 'PROPOSED')
  const proposedIds = new Set(proposed.map((l) => l.id))

  const suggest = useMutation({
    mutationFn: async () => waitForJob(await raw.post<Job>(`${V1}/clients/${clientId}/review-queue/suggest/`)),
    onSuccess: async (job) => {
      await invalidate()
      // The reading happens a few rows at a time while this client is open; the strip above shows it.
      const r = job.result as { waiting_for_assistant?: number }
      const n = r?.waiting_for_assistant ?? 0
      toast.success(n ? `${plural(n, 'row')} queued for the assistant` : 'Nothing to queue', {
        description: n ? 'It reads them a few at a time while this client is open. They appear here as it goes.' : undefined,
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
      const el = document.getElementById(`row-${next.id}`)
      // The table is one Tab stop; when the person is in it, focus travels with the selection.
      if (el && tableRef.current?.contains(document.activeElement)) el.focus({ preventScroll: true })
      el?.scrollIntoView({ block: 'nearest' })
    }
  }
  useHotkey('j', 'Next row', () => move(1), 'Review')
  useHotkey('arrowdown', 'Next row', () => move(1), 'Review')
  useHotkey('k', 'Previous row', () => move(-1), 'Review')
  useHotkey('arrowup', 'Previous row', () => move(-1), 'Review')
  useHotkey('/', 'Search the queue', () => document.getElementById('review-search')?.focus(), 'Review')
  useHotkey('x', 'Tick the current row for posting', () => {
    if (!selected || !canPost || stage === 'unresolved' || !postable(selected)) return
    setTicked((t) => {
      const next = new Set(t)
      if (next.has(selected.id)) next.delete(selected.id)
      else next.add(selected.id)
      return next
    })
  }, 'Review')

  const highCount = summary.data?.bulk_approvable ?? 0
  const needSettling = summary.data?.needs_settlement ?? 0
  // The rows the band would post, for the confirmation's breakdown. The "Ready to post" list is the one that holds them.
  const ready = useQuery({ ...reviewQueue(clientId, 'pending_approval'), enabled: canPost && highCount > 0 })
  function askBulk() {
    const detail = ready.data ? summariseBulk(ready.data) : null
    setBulk({ count: highCount, summary: detail && detail.count === highCount ? detail : null })
    setConfirmHigh(true)
  }
  const bankLedgerOf = (row: Classification) => accounts.data?.results.find((a) => a.id === row.transaction.bank_account)?.ledger_name

  return (
    <div className="grid gap-4">
      {needSettling > 0 && stage !== 'unresolved' && (
        <p role="status" className="rounded-md border border-accent-edge bg-accent px-3 py-2 text-sm">
          {plural(needSettling, 'row')} {needSettling === 1 ? 'is' : 'are'} on a supplier’s or customer’s own account. Each needs you to say which
          bills it settles, so {needSettling === 1 ? 'it is' : 'they are'} not part of “Post all”. Open the row to settle it.
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <StageNav clientId={clientId} active={stage} />
        <div className="flex flex-wrap gap-2">
          {can('transaction.classify') && (
            <Button variant="outline" onClick={() => suggest.mutate()} disabled={suggest.isPending || !summary.data?.unresolved}>
              <Sparkles /> {suggest.isPending ? 'Asking the assistant…' : 'Ask assistant to suggest'}
            </Button>
          )}
          {canPost && highCount > 0 && (
            <Button variant={tickedRows.length ? 'outline' : 'primary'} onClick={askBulk}>
              <CheckCheck /> Post all high-confidence ({highCount})
            </Button>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground">{STAGES.find((s) => s.stage === stage)?.hint}</p>

      <AssistantStrip clientId={clientId} />

      {proposed.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-info/30 bg-info-bg px-4 py-2.5 text-sm">
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

      {!queue.isPending && !queue.error && (queue.data?.length ?? 0) > 0 && (
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            id="review-search"
            type="search"
            aria-label="Search the queue by narration, payee, ledger or amount"
            placeholder="Search narration, payee, ledger, amount"
            className="pl-8"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
      )}

      {queue.isPending ? (
        <Spinner label="Loading the queue…" />
      ) : queue.error ? (
        <ErrorState error={queue.error} retry={() => void queue.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title={text.trim() ? `Nothing matches “${text.trim()}”` : stage === 'unresolved' ? 'Every transaction has a ledger' : 'Nothing is waiting here'}>
          {text.trim() ? (
            <button type="button" className="underline" onClick={() => setText('')}>
              Clear the search
            </button>
          ) : stage === 'unresolved' && (summary.data?.pending_approval ?? 0) > 0 ? (
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
          <Card className="relative max-h-[70vh] overflow-auto overscroll-contain">
            {canPost && tickedRows.length > 0 && (
              <div className="sticky top-0 z-20 flex items-center gap-3 border-b bg-accent px-3 py-1.5 text-[13px]" role="status">
                <span className="font-semibold">{tickedRows.length} selected</span>
                <Button size="sm" onClick={() => setConfirmTicked(true)}>
                  <CheckCheck /> Post
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setTicked(new Set())}>
                  Clear
                </Button>
              </div>
            )}
            <table ref={tableRef} className="w-full text-left text-sm">
              <thead className={cn('sticky z-10 border-b bg-surface-2 text-xs text-muted-foreground', canPost && tickedRows.length > 0 ? 'top-9' : 'top-0')}>
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
                  <SortTh label="Date" sortKey="date" sort={sort} onSort={toggleSort} className="px-3" />
                  <th className="px-3 py-2 font-semibold">Narration</th>
                  <SortTh label="Withdrawal" sortKey="amount" sort={sort} onSort={toggleSort} className="w-px px-2 text-right" right />
                  <th className="w-px px-2 py-2 text-right font-semibold">Deposit</th>
                  <th className="w-44 px-3 py-2 font-semibold max-sm:hidden">Ledger</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    id={`row-${r.id}`}
                    onClick={() => {
                      setSelectedId(r.id)
                      if (phone) setSheet(true)
                    }}
                    onFocus={(e) => e.target === e.currentTarget && setSelectedId(r.id)}
                    onKeyDown={(e) => {
                      // Space ticks the row from the row itself; typing in a control inside it is left alone.
                      if (e.key === ' ' && e.target === e.currentTarget && canPost && stage !== 'unresolved' && postable(r)) {
                        e.preventDefault()
                        setTicked((t) => {
                          const n = new Set(t)
                          if (n.has(r.id)) n.delete(r.id)
                          else n.add(r.id)
                          return n
                        })
                      }
                    }}
                    // One Tab stop for the whole table: only the selected row can be tabbed to.
                    tabIndex={r.id === selected?.id ? 0 : -1}
                    aria-selected={r.id === selected?.id}
                    className={cn('h-(--row-h) cursor-pointer border-b focus-visible:outline-offset-[-2px]', r.id === selected?.id ? 'bg-accent shadow-[inset_3px_0_0_var(--primary)]' : 'hover:bg-hover')}
                  >
                    {canPost && stage !== 'unresolved' && (
                      <td className="px-3" onClick={(e) => e.stopPropagation()}>
                        {postable(r) && (
                          <Checkbox
                            aria-label={`Select ${rowName(r)}`}
                            tabIndex={-1}
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
                    <td className="num whitespace-nowrap px-3 py-1">{formatDate(r.transaction.value_date)}</td>
                    <td className="min-w-40 max-w-0 px-3 py-1" title={r.transaction.narration}>
                      <div className="truncate">
                        {r.counterparty && <span className="font-medium text-heading">{r.counterparty} </span>}
                        <span className="font-mono text-xs text-muted-foreground">{r.transaction.narration}</span>
                      </div>
                      {r.ledger_name && <div className="truncate text-xs text-muted-foreground sm:hidden">{r.ledger_name}</div>}
                    </td>
                    <td className="num whitespace-nowrap px-2 py-1 text-right">{r.transaction.is_debit ? r.transaction.amount_display : ''}</td>
                    <td className="num whitespace-nowrap px-2 py-1 text-right">{!r.transaction.is_debit ? r.transaction.amount_display : ''}</td>
                    <td className="px-3 py-1 max-sm:hidden">
                      {r.ledger_name ? (
                        <span className="flex items-center gap-1.5">
                          <span className="max-w-[14ch] truncate" title={r.ledger_name}>{r.ledger_name}</span>
                          {proposedIds.has(r.ledger ?? '') && (
                            <span className="shrink-0 rounded-sm bg-info-bg px-1 text-[11px] font-medium text-info" title="A new ledger the assistant proposed. A senior CA accepts it before rows can go in.">
                              New
                            </span>
                          )}
                          {DOT[r.review_band] && r.method !== 'REVIEWED' && (
                            <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground" title={DOT[r.review_band]!.title}>
                              <span aria-hidden className={cn('size-2 rounded-full', DOT[r.review_band]!.className)} />
                              {DOT[r.review_band]!.word}
                              <span className="sr-only"> confidence: {DOT[r.review_band]!.title}</span>
                            </span>
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

          {selected && !phone && (
            <Decision
              key={selected.id}
              clientId={clientId}
              row={selected}
              ledgers={usableLedgers(ledgers.data, bankLedgerOf(selected))}
              allLedgers={ledgers.data ?? []}
              canPost={canPost}
              onDone={() => move(0)}
            />
          )}
          {selected && phone && (
            <Dialog open={sheet} onOpenChange={setSheet}>
              <DialogContent className="p-4" aria-describedby={undefined}>
                <DialogTitle className="sr-only">Decide this row</DialogTitle>
                <DialogDescription className="sr-only">Choose the ledger, then place and post the row.</DialogDescription>
                <Decision
                  key={selected.id}
                  clientId={clientId}
                  row={selected}
                  ledgers={usableLedgers(ledgers.data, bankLedgerOf(selected))}
                  allLedgers={ledgers.data ?? []}
                  canPost={canPost}
                  flat
                  onDone={() => move(0)}
                />
              </DialogContent>
            </Dialog>
          )}
        </div>
      )}

      <Confirm
        open={confirmHigh}
        onOpenChange={setConfirmHigh}
        title={`Post ${plural(bulk.count, 'high-confidence row')}?`}
        confirmLabel={`Post ${bulk.count}`}
        onConfirm={() => post({ band: 'HIGH' })}
      >
        {bulk.summary ? (
          <>
            <p>
              {[
                bulk.summary.byRule ? `${plural(bulk.summary.byRule, 'row')} placed by the client’s rules` : '',
                bulk.summary.byModel ? `${plural(bulk.summary.byModel, 'row')} placed by the language model` : '',
                bulk.summary.byPerson ? `${plural(bulk.summary.byPerson, 'row')} placed by a person` : '',
              ]
                .filter(Boolean)
                .join(', ')}
              .
            </p>
            <p className="num">
              {[
                bulk.summary.paidOut ? `${plural(bulk.summary.paidOut, 'payment')} out, ${formatPaise(bulk.summary.paidOutPaise)}` : '',
                bulk.summary.received ? `${plural(bulk.summary.received, 'receipt')} in, ${formatPaise(bulk.summary.receivedPaise)}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            {bulk.summary.byModel > 0 && (
              <p>Rows placed by the language model are guesses from the narration. Look at them first if you have not.</p>
            )}
          </>
        ) : (
          <p>Placed with high confidence by the client’s rules or the language model.</p>
        )}
        <p>
          Each becomes a journal entry in the Day Book. Until the books are signed off you can still correct or remove any of them.
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

function SortTh({
  label,
  sortKey,
  sort,
  onSort,
  className,
  right,
}: {
  label: string
  sortKey: SortKey
  sort: Sort
  onSort: (key: SortKey) => void
  className?: string
  right?: boolean
}) {
  const on = sort?.key === sortKey
  const Icon = !on ? ArrowUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={cn('py-2 font-medium', className)} aria-sort={on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn('inline-flex items-center gap-1 rounded-sm hover:text-foreground', right && 'flex-row-reverse')}
        title={sortKey === 'amount' ? 'Sort by amount (withdrawals and deposits together)' : `Sort by ${label.toLowerCase()}`}
      >
        {label}
        <Icon className={cn('size-3', !on && 'opacity-50')} aria-hidden />
      </button>
    </th>
  )
}

/** Everything needed to decide one row, and the two actions: place it, and post it. */
function Decision({
  clientId,
  row,
  ledgers,
  allLedgers,
  canPost,
  flat,
  onDone,
}: {
  clientId: string
  row: Classification
  ledgers: ReturnType<typeof usableLedgers>
  /** Every ledger including the proposed ones, so a proposal the row points at can be shown and decided here. */
  allLedgers: ReturnType<typeof usableLedgers>
  canPost: boolean
  /** Inside a sheet: no card of its own, no sticky positioning. */
  flat?: boolean
  onDone: () => void
}) {
  const { can } = useSession()
  const parties = useQuery(partiesQuery(clientId))
  const invalidate = useInvalidateClient(clientId)
  const queryClient = useQueryClient()
  const ledgerInput = useRef<HTMLInputElement>(null)
  const suggested = ledgers.some((l) => l.id === row.ledger) ? row.ledger : null
  const proposal = allLedgers.find((l) => l.id === row.ledger && l.status === 'PROPOSED') ?? null
  const [deciding, setDeciding] = useState(false)
  const [ledger, setLedger] = useState<string | null>(suggested)
  const [party, setParty] = useState<string>(row.party ?? '')
  const [tds, setTds] = useState<string>(row.tds_section ?? '')
  const [rcm, setRcm] = useState(row.rcm)
  const [learn, setLearn] = useState(!row.is_self_transfer && !!row.counterparty)
  const [busy, setBusy] = useState(false)
  const t = row.transaction
  const canPlace = can('transaction.classify')
  const mayUndoRule = can('suggestion.edit')
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
      const placedIn = result.classification.ledger_name
      const ruleId = learn ? result.rule_learned : null
      // Undo deletes the rule and nothing else, so it is offered only when the rule is all this decision did.
      const created = !!ruleId && result.rule_created && mayUndoRule && !result.also_placed && !result.also_revised && !result.auto_posted
      const extra = [
        ruleId ? `Rule saved: ${row.counterparty} to ${placedIn}` : '',
        learn && !ruleId ? 'Nothing was remembered: no payee could be read' : '',
        result.also_placed ? `${plural(result.also_placed, 'other row')} from the same payee placed too` : '',
        result.auto_posted ? `${result.auto_posted} posted automatically` : '',
      ].filter(Boolean)
      toast.success(`Placed in ${placedIn}`, {
        description: extra.join(' · ') || undefined,
        // Undo removes the rule only; rows it already placed stay where they are.
        ...(created && ruleId
          ? {
              duration: 10_000,
              action: {
                label: 'Undo',
                onClick: () =>
                  void raw
                    .delete(`${V1}/clients/${clientId}/rules/${ruleId}/`)
                    .then(() => queryClient.invalidateQueries({ queryKey: rulesQuery(clientId).queryKey }))
                    .then(() => toast.info('Rule removed', { description: 'Rows already placed stay where they are.' }))
                    .catch((e: unknown) => toast.error(messageOf(e))),
              },
            }
          : {}),
      })
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
  useHotkey('p', 'Post this row', () => canPost && row.ledger && unchanged && !busy && !row.on_party_account && void postNow(), 'Review')

  // The entry as it will be posted with what is chosen now, not as it was suggested.
  const chosenLedger = ledgers.find((l) => l.id === ledger)
  const chosenParty = parties.data?.find((p) => p.id === party)
  const legs = (row.entry_legs ?? []).map((leg) => (leg.is_bank ? leg : { ...leg, ledger: chosenLedger?.name ?? null }))
  const extras = [chosenParty?.canonical_name, tds && `TDS ${tds}`, rcm && 'Reverse charge'].filter(Boolean).join(' · ')
  return (
    <Card className={cn('grid content-start gap-4 p-4', flat ? 'border-0 p-0 shadow-none' : 'xl:sticky xl:top-20 xl:max-h-[calc(100svh-6rem)] xl:overflow-auto xl:overscroll-contain')}>
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
        <div className="flex gap-2 rounded-md border border-accent-edge bg-accent p-2.5 text-sm">
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

      {proposal && (
        <div className="grid gap-2 rounded-md border border-info/30 bg-info-bg p-3 text-sm">
          <div>
            <Bot className="mr-1.5 inline size-4 text-info" aria-hidden />
            The assistant suggests opening a <strong>new ledger, “{proposal.name}”</strong>
            {proposal.group ? ` (${GROUP_LABEL[proposal.group] ?? proposal.group})` : ''} for this row.
            {proposal.proposal_reason ? <span className="block text-muted-foreground">{proposal.proposal_reason}</span> : null}
          </div>
          {can('journal.approve') ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => setDeciding(true)}>Accept, merge or reject</Button>
              <span className="text-xs text-muted-foreground">Or choose another ledger below.</span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">A senior CA accepts it before this row can go in it. You can choose another ledger below.</p>
          )}
        </div>
      )}
      {deciding && proposal && <ProposalDecision clientId={clientId} proposal={proposal} existing={ledgers} onClose={() => setDeciding(false)} />}

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

          {row.counterparty && !row.is_self_transfer ? (
            <Checkbox
              className="-mt-1.5 items-start [&>input]:mt-0.5"
              label={`Also place future ${t.is_debit ? 'payments to' : 'receipts from'} ${row.counterparty} in ${chosenLedger?.name ?? 'the ledger you choose'}`}
              checked={learn}
              onChange={(e) => setLearn(e.target.checked)}
            />
          ) : (
            <p className="-mt-1.5 text-xs text-muted-foreground">
              {row.is_self_transfer
                ? 'A transfer between the client’s own accounts is decided each time, so nothing is remembered.'
                : 'The payee could not be read from this narration, so this decision applies to this row only. Add a rule in Masters if it repeats.'}
            </p>
          )}

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

          {canPost && row.ledger && unchanged && row.on_party_account && (
            <SettlementPanel clientId={clientId} row={row} onDone={onDone} />
          )}

          <div className="sticky bottom-0 -mx-4 flex flex-wrap justify-end gap-2 border-t bg-card px-4 py-3 max-sm:[&>*]:flex-1">
            {!alreadyPlacedByPerson && (
              <Button variant={row.ledger && unchanged ? 'outline' : 'primary'} onClick={() => void place()} disabled={busy || !ledger}>
                {row.ledger && ledger === row.ledger ? 'Confirm ledger' : 'Place in ledger'} <Kbd className="ml-1 bg-transparent max-sm:hidden">Enter</Kbd>
              </Button>
            )}
            {canPost && row.ledger && unchanged && !row.on_party_account && (
              <Button onClick={() => void postNow()} disabled={busy}>
                Post entry <Kbd className="ml-1 bg-transparent text-primary-foreground/80 max-sm:hidden">P</Kbd>
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
