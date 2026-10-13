// Deciding where each bank transaction goes, then posting it.
//
// Two stages, kept visibly apart because the server keeps them apart: a row is first PLACED
// in a ledger (by a rule, the assistant, or you), and then POSTED, which writes the journal
// entry. "Needs a ledger" is the work; "Ready to post" is the check before it enters the
// books. The queue is one list and the decision opens inline under the selected row, so a phone
// and a desktop read the same; the keyboard moves through it as fast as a CA reads: J/K to move,
// L for the ledger, Enter to place, P to post.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { AlertTriangle, ArrowUp, Bot, Brain, CheckCheck, Link2, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from '@/lib/toast'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { waitForJob } from '@/api/jobs'
import { ledgers as ledgersQuery, parties as partiesQuery, reviewQueue, rules as rulesQuery, type ReviewTab, type Stage } from '@/api/queries/books'
import { bankAccounts, clientDetail, reviewSummary, useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, TDS_SECTIONS, type Classification, type Party, type Job, type JournalEntry, type PlacementResult } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { Pager, usePaged } from '@/components/ca/Pager'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Collapse, useClosing } from '@/components/ui/collapse'
import { GlideChips } from '@/components/ui/glide-chips'
import { AssistantStrip } from '@/features/assistant/AssistantStrip'
import { useAssistantStatus } from '@/features/assistant/useAssistant'
import { isProcessing } from '@/features/assistant/queue'
import { Checkbox, Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Kbd } from '@/components/ui/kbd'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatPaise, plainAmount, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { isHighReady, summariseBulk, type BulkSummary } from './bulkPost'
import { LedgerIdeasBanner } from './LedgerIdeasBanner'
import { SimilarGroupList } from './SimilarGroupList'
import { groupKeyOf, groupSimilar, type SimilarGroup } from './similarGroups'
import { SettlementPanel } from './SettlementPanel'
import { LedgerIdea } from './LedgerIdea'
import { StatementPicker } from './StatementPicker'
import { useReviewScope } from './useReviewScope'
import { setSearchAllStatements, useSearchAllStatements } from '@/lib/reviewPrefs'
import { LedgerPicker, usableLedgers } from './LedgerPicker'
import { NewAccountDialog } from './NewAccountDialog'
import { ProposalDecision } from '@/features/masters/MastersScreen'
import { usePageSize } from '@/lib/pageSizes'
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
export function ReviewScreen({ clientId, stage, statement }: { clientId: string; stage?: ReviewTab; statement?: string }) {
  if (stage === 'posted') return <PostedEntries clientId={clientId} />
  return <ReviewQueue clientId={clientId} stage={stage} statement={statement} />
}

function ReviewQueue({ clientId, stage: asked, statement: askedStatement }: { clientId: string; stage?: Stage; statement?: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const summary = useQuery(reviewSummary(clientId))
  // Reviewed by bank statement: the statements with rows waiting, the ones chosen (one, several or all), and the numbers for them.
  const scope = useReviewScope(clientId, askedStatement)
  const choices = scope.waiting
  const chosenStatements = scope.selection
  const counts = scope.counts
  // Opened without saying which stage: go where the work is, in the statements chosen.
  const firstNeeds = counts ? counts.unresolved : summary.data?.unresolved
  const firstReady = counts ? counts.pending_approval : summary.data?.pending_approval
  const stage: Stage = asked ?? (!firstNeeds && firstReady ? 'pending_approval' : 'unresolved')
  const queue = useQuery(reviewQueue(clientId, stage))
  const navigate = useNavigate()
  const statementLabel = useMemo(() => new Map(choices.map((c) => [c.id, c.label])), [choices])
  const searchAll = useSearchAllStatements()
  const ledgers = useQuery(ledgersQuery(clientId))
  const accounts = useQuery(bankAccounts(clientId))
  const invalidate = useInvalidateClient(clientId)

  const working = isProcessing(useAssistantStatus(clientId))
  const [band, setBand] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [confirmHigh, setConfirmHigh] = useState(false)
  // Frozen when the dialog opens: the live count drops to 0 the moment the posting succeeds.
  const [bulk, setBulk] = useState<{ count: number; summary: BulkSummary | null }>({ count: 0, summary: null })
  const [confirmTicked, setConfirmTicked] = useState(false)
  // Alike rows seen as groups, one decision each; and one group's rows when it is opened.
  const [view, setView] = useState<'rows' | 'groups'>('rows')
  const [groupKey, setGroupKey] = useState<string | null>(null)
  const [confirmGroup, setConfirmGroup] = useState<SimilarGroup | null>(null)
  const [text, setText] = useState('')
  // A search looks through every row of the statement being reviewed (not only the page shown); with the setting on, through every statement.
  const statements = searchAll && text.trim() ? null : chosenStatements
  const statementKey = statements ? statements.join(',') : 'all'
  const [sort, setSort] = useState<Sort>(null)
  const listRef = useRef<HTMLUListElement>(null)
  // The open row can be shut again by pressing it, without losing which row the keys are on.
  const [collapsed, setCollapsed] = useState(false)

  const rows = useMemo(() => {
    const q = text.trim().toLowerCase()
    const qa = plainAmount(q)
    const kept = (queue.data ?? [])
      .filter((r) => !statements || statements.includes(r.transaction.statement))
      .filter((r) => !band || r.review_band === band)
      .filter((r) => !groupKey || groupKeyOf(r) === groupKey)
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
  }, [queue.data, statementKey, band, text, sort, groupKey]) // eslint-disable-line react-hooks/exhaustive-deps
  // A long queue shows a page of rows at a time; what the list is of (stage, filter, search, sort) decides when it goes back to page 1.
  const groups = useMemo(() => groupSimilar(rows), [rows])
  const pager = usePaged(rows, `${stage}|${statementKey}|${band}|${text}|${sort?.key ?? ''}${sort?.dir ?? ''}`, usePageSize('review'))
  const toggleSort = (key: SortKey) =>
    setSort((s) => (s?.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null))
  const index = Math.max(0, rows.findIndex((r) => r.id === selectedId))
  const selected = rows[index] ?? null
  const openId = selected && !collapsed ? selected.id : null
  const closing = useClosing(openId)
  const choose = (id: string) => {
    if (id === selected?.id) setCollapsed((c) => !c)
    else {
      setSelectedId(id)
      setCollapsed(false)
    }
  }
  // Keep a row selected: the first one on arrival, and the one now in the same place after a row leaves.
  useEffect(() => {
    if (rows.length && !rows.some((r) => r.id === selectedId)) setSelectedId(rows[Math.min(index, rows.length - 1)]!.id)
  }, [rows, selectedId, index])
  // The selected row's page is the one shown (keys, or a row leaving, can move the selection to another page) ...
  useEffect(() => {
    if (selectedId && rows.length) pager.reveal(index)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])
  // ... and turning the page by hand selects the first row on it, so the keys and the open row are on the page in view.
  useEffect(() => {
    if (pager.items.length && !pager.items.some((r) => r.id === selectedId)) setSelectedId(pager.items[0]!.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pager.page])
  useEffect(() => setTicked(new Set()), [stage, band, statementKey])
  // A filter or a sort changes what is listed; a short fade says so without remounting the rows.
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    listRef.current?.animate?.([{ opacity: 0.35 }, { opacity: 1 }], { duration: 180, easing: 'ease-out' })
  }, [band, sort, pager.page])
  // The decision opens under its row; keep the whole of it on screen when the selection moves.
  useEffect(() => {
    if (!selectedId) return
    // After it has finished opening, so the whole of it is measured.
    const timer = setTimeout(() => document.getElementById(`decision-${selectedId}`)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }), 300)
    return () => clearTimeout(timer)
  }, [selectedId])

  const canPost = can('journal.approve') && !!client.data?.can_post
  // A row on a party's account is never ticked or posted in bulk: a person says which bills it settles, one row at a time.
  const postable = (r: Classification) => !!r.ledger && !r.is_posted && !r.on_party_account
  const tickedRows = rows.filter((r) => ticked.has(r.id) && postable(r))
  const postableCount = rows.filter(postable).length
  // Ledgers the assistant added: still waiting for a CA (PROPOSED), or live already but not yet looked at.
  const proposed = (ledgers.data ?? []).filter((l) => l.status === 'PROPOSED' || l.awaiting_look)
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
      setCollapsed(false)
      const el = document.getElementById(`row-${next.id}`)
      // When the person is in the list, focus travels with the selection.
      if (el && listRef.current?.contains(document.activeElement)) el.focus({ preventScroll: true })
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

  const needSettling = counts ? counts.settling : (summary.data?.needs_settlement ?? 0)
  const needsCount = counts ? counts.unresolved : (summary.data?.unresolved ?? 0)
  const readyCount = counts ? counts.pending_approval : (summary.data?.pending_approval ?? 0)
  const totalCount = counts ? counts.all : (summary.data?.total ?? 0)
  // Reviewing one statement: "post all" is that statement's high-confidence rows only, so what was checked is what is posted. With no
  // statement chosen (a single statement, or all of them) it is the whole client's, as before.
  const clientHigh = summary.data?.bulk_approvable ?? 0
  // The rows the band would post, for the confirmation's breakdown. The "Ready to post" list is the one that holds them.
  const ready = useQuery({ ...reviewQueue(clientId, 'pending_approval'), enabled: canPost && clientHigh > 0 })
  const scopedHigh = useMemo(
    () => (chosenStatements ? (ready.data ?? []).filter((r) => isHighReady(r) && chosenStatements.includes(r.transaction.statement)) : null),
    [ready.data, chosenStatements],
  )
  const highCount = scopedHigh ? scopedHigh.length : clientHigh
  function askBulk() {
    const detail = scopedHigh ? summariseBulk(scopedHigh) : ready.data ? summariseBulk(ready.data) : null
    setBulk({ count: highCount, summary: detail && detail.count === highCount ? detail : null })
    setConfirmHigh(true)
  }
  const bankLedgerOf = (row: Classification) => accounts.data?.results.find((a) => a.id === row.transaction.bank_account)?.ledger_name

  return (
    <div className="grid gap-4">
      {needSettling > 0 && stage !== 'unresolved' && (
        <p role="status" className="rounded-xl border border-accent-edge bg-accent px-4 py-3 text-sm text-accent-foreground">
          {plural(needSettling, 'row')} {needSettling === 1 ? 'is' : 'are'} on a supplier’s or customer’s own account. Each needs you to say which
          bills it settles, so {needSettling === 1 ? 'it is' : 'they are'} not part of “Post all”. Open the row to settle it.
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <StageNav clientId={clientId} active={stage} />
        <div className="flex flex-wrap gap-2">
          {canPost && highCount > 0 && (
            <Button variant={tickedRows.length ? 'outline' : 'primary'} onClick={askBulk}>
              <CheckCheck /> Post all high-confidence{scopedHigh ? (chosenStatements!.length > 1 ? ' in these statements' : ' in this statement') : ''} ({highCount})
            </Button>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground">{STAGES.find((s) => s.stage === stage)?.hint}</p>

      {choices.length > 1 && (
        <StatementPicker
          choices={choices}
          selection={chosenStatements}
          total={choices.reduce((n, c) => n + c.count, 0)}
          onChange={(next) => void navigate({ to: '.', search: ((prev: Record<string, unknown>) => ({ ...prev, statement: next })) as never, replace: true })}
        />
      )}
      {choices.length > 1 && searchAll && text.trim() && chosenStatements && (
        <p role="status" className="text-xs text-muted-foreground">
          Searching every statement. Turn this off with “Search all statements”, or in Preferences.
        </p>
      )}

      <AssistantStrip clientId={clientId} />

      {stage === 'unresolved' && <LedgerIdeasBanner clientId={clientId} rows={rows} canPlace={can('transaction.classify')} canCreate={can('ledger.manage')} />}

      {groupKey && (
        <p role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          Showing the rows of one group.
          <button type="button" className="font-medium text-link underline underline-offset-2" onClick={() => setGroupKey(null)}>
            Show every row
          </button>
          <button
            type="button"
            className="font-medium text-link underline underline-offset-2"
            onClick={() => {
              setGroupKey(null)
              setView('groups')
            }}
          >
            Back to the groups
          </button>
        </p>
      )}

      {proposed.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-info/30 bg-info-bg px-4 py-3 text-sm text-info">
          <span>
            <Bot className="mr-1.5 inline size-4 text-info" aria-hidden />
            The assistant added {plural(proposed.length, 'new ledger')} ({proposed.slice(0, 3).map((l) => l.name).join(', ')}
            {proposed.length > 3 ? '…' : ''}). Check each name.
          </span>
          <Button asChild size="sm" variant="outline">
            <Link to="/clients/$clientId/ledgers" params={{ clientId }}>
              Look at them
            </Link>
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        {stage !== 'unresolved' ? (
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Confidence:</span>
            <GlideChips
              label="Confidence"
              value={band}
              onChange={setBand}
              options={['', 'HIGH', 'ADVISED', 'JUDGEMENT'].map((b) => ({ value: b, label: b ? BAND_LABEL[b]!.label : 'Any' }))}
            />
          </div>
        ) : (
          <span />
        )}
        <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
          {canPost && stage !== 'unresolved' && (groups.length > 0 || view === 'groups') && (
            <GlideChips
              label="How to see the rows"
              variant="segmented"
              value={view}
              onChange={(next) => {
                setView(next)
                setGroupKey(null)
              }}
              options={[
                { value: 'rows', label: 'Rows' },
                { value: 'groups', label: `Similar groups · ${groups.length}` },
              ]}
            />
          )}
          {can('transaction.classify') && needsCount > 0 && (
            <Button variant="outline" onClick={() => suggest.mutate()} loading={suggest.isPending}>
              {!suggest.isPending && <Sparkles />} {suggest.isPending ? 'Asking the assistant…' : `Suggest ledgers for ${plural(needsCount, 'row')}`}
            </Button>
          )}
          {!queue.isPending && !queue.error && (queue.data?.length ?? 0) > 1 && (
            <div className="flex items-center gap-1.5 text-sm" role="group" aria-label="Sort the rows">
              <span className="text-muted-foreground">Sort</span>
              <SortChip label="Date" sortKey="date" sort={sort} onSort={toggleSort} />
              <SortChip label="Amount" sortKey="amount" sort={sort} onSort={toggleSort} />
            </div>
          )}
          {!queue.isPending && !queue.error && (queue.data?.length ?? 0) > 0 && (
            <div className="relative w-full min-w-56 max-w-sm flex-1">
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
          {choices.length > 1 && !queue.isPending && !queue.error && (
            <Checkbox
              className="text-sm text-muted-foreground"
              label="Search all statements"
              checked={searchAll}
              onChange={(e) => setSearchAllStatements(e.target.checked)}
            />
          )}
        </div>
      </div>

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
          ) : stage === 'unresolved' && readyCount > 0 ? (
            <>
              {plural(readyCount, 'row')} placed and ready to post.{' '}
              <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'pending_approval' }} className="underline">
                Go to Ready to post
              </Link>
              .
            </>
          ) : totalCount === 0 ? (
            'Everything uploaded is posted. Upload the next statement, or read the reports.'
          ) : null}
        </EmptyState>
      ) : view === 'groups' && stage !== 'unresolved' ? (
        <SimilarGroupList
          groups={groups}
          canPost={canPost}
          onPost={setConfirmGroup}
          onShow={(g) => {
            setGroupKey(g.key)
            setView('rows')
          }}
        />
      ) : (
        <div className="relative overflow-hidden rounded-xl border border-border-strong bg-surface-2">
          {canPost && tickedRows.length > 0 && (
            <div className="flex items-center gap-3 border-b border-border-strong bg-accent px-4 py-2 text-[13px] text-accent-foreground" role="status">
              <span className="font-semibold">{tickedRows.length} selected</span>
              <Button size="sm" onClick={() => setConfirmTicked(true)}>
                <CheckCheck /> Post
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setTicked(new Set())}>
                Clear
              </Button>
            </div>
          )}
          {canPost && stage !== 'unresolved' && postableCount > 1 && (
            <label className="flex items-center gap-3 border-b border-border-strong px-4 py-2 text-[13px] text-muted-foreground">
              <Checkbox
                aria-label="Tick every row that can be posted"
                checked={rows.filter(postable).every((r) => ticked.has(r.id))}
                onChange={(e) => setTicked(e.target.checked ? new Set(rows.filter(postable).map((r) => r.id)) : new Set())}
              />
              Select every row that can be posted
            </label>
          )}
          <ul ref={listRef} id="review-list" aria-label="Rows waiting" className="divide-y divide-border-strong">
            {pager.items.map((r) => {
              const isOpen = r.id === openId
              const showBody = isOpen || closing === r.id
              const tickable = canPost && stage !== 'unresolved' && postable(r)
              return (
                <li
                  key={r.id}
                  data-open={isOpen}
                  className={cn('relative transition-colors duration-200', isOpen ? 'bg-hover shadow-[inset_3px_0_0_var(--primary)]' : 'hover:bg-hover/60')}
                >
                  <div className="flex items-stretch">
                    {canPost && stage !== 'unresolved' && (
                      <div className="grid w-12 shrink-0 place-items-center">
                        {tickable && (
                          <Checkbox
                            aria-label={`Select ${rowName(r)}`}
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
                      </div>
                    )}
                    <button
                      id={`row-${r.id}`}
                      type="button"
                      aria-expanded={isOpen}
                      aria-controls={`decision-${r.id}`}
                      onClick={() => choose(r.id)}
                      className={cn(
                        'grid min-w-0 flex-1 grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 py-4 pr-5 text-left max-sm:grid-cols-[minmax(0,1fr)_auto]',
                        canPost && stage !== 'unresolved' ? 'pl-0' : 'pl-5',
                      )}
                    >
                      <span className="num font-mono text-[13px] text-muted-foreground max-sm:col-span-2">{formatDate(r.transaction.value_date)}</span>
                      <span className="min-w-0">
                        <span className="block truncate" title={r.transaction.narration}>
                          {r.counterparty && <span className="font-medium text-heading">{r.counterparty} </span>}
                          <span className="font-mono text-xs text-muted-foreground">{r.transaction.narration}</span>
                          {choices.length > 1 && (!statements || statements.length > 1) && statementLabel.get(r.transaction.statement) && (
                            <span className="ml-2 text-xs text-faint"> · {statementLabel.get(r.transaction.statement)}</span>
                          )}
                        </span>
                        <span className="mt-0.5 flex items-center gap-1.5 text-[13px]">
                          {r.ledger_name ? (
                            <>
                              <span className="truncate text-heading" title={r.ledger_name}>
                                {r.ledger_name}
                              </span>
                              {r.memory && r.method !== 'REVIEWED' && (
                                <Badge tone={r.memory.kind === 'ai' ? 'assistant' : 'neutral'} title={r.memory.note} className="shrink-0">
                                  {r.memory.kind === 'ai' ? 'Assistant' : r.memory.kind === 'matched' ? 'Invoice' : 'Rule'}
                                  <span className="sr-only">
                                    {' '}
                                    {r.memory.label}: {r.memory.note}
                                  </span>
                                </Badge>
                              )}
                              {r.suggested_ledger && r.method !== 'REVIEWED' && (
                                <span className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-info-bg px-1 text-xs font-medium text-info" title={`The assistant suggests a better ledger: ${r.suggested_ledger.name}. Open the row to create it or place the row there.`}>
                                  <Sparkles className="size-3" aria-hidden />
                                  Ledger idea
                                </span>
                              )}
                              {proposedIds.has(r.ledger ?? '') && (
                                <span className="shrink-0 rounded-sm bg-info-bg px-1 text-xs font-medium text-info" title="A new ledger the assistant added. A senior CA keeps it, renames it or merges it into an existing one.">
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
                            </>
                          ) : r.model_state === 'claimed' && working ? (
                            // The assistant has this row right now: a quiet pulse where its ledger will appear.
                            <span role="status" className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                              <span aria-hidden className="block h-2.5 w-28 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
                              <span className="sr-only">Being read by the assistant</span>
                            </span>
                          ) : r.model_state === 'waiting' && working ? (
                            <span className="text-xs text-muted-foreground">In line for the assistant</span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-edge bg-accent px-2 py-0.5 text-xs font-medium text-accent-foreground">
                              <span aria-hidden className="size-1.5 rounded-full bg-current" />
                              Needs a ledger
                            </span>
                          )}
                        </span>
                      </span>
                      <span className="text-right">
                        <span className="num block font-mono text-heading">{r.transaction.amount_display}</span>
                        <span className="sr-only">{r.transaction.is_debit ? 'Withdrawal' : 'Deposit'}</span>
                      </span>
                    </button>
                  </div>
                  {showBody && (
                    <div id={`decision-${r.id}`}>
                      <Collapse open={isOpen}>
                        <div className="px-5 pb-5 pt-1">
                          <Decision
                            key={r.id}
                            clientId={clientId}
                            row={r}
                            ledgers={usableLedgers(ledgers.data, bankLedgerOf(r))}
                            allLedgers={ledgers.data ?? []}
                            canPost={canPost}
                            flat
                            onDone={() => move(0)}
                          />
                        </div>
                      </Collapse>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
          <Pager paged={pager} label="Rows waiting" scrollTo="review-list" />
        </div>
      )}

      <Confirm
        open={confirmHigh}
        onOpenChange={setConfirmHigh}
        title={`Post ${plural(bulk.count, 'high-confidence row')}${scopedHigh ? (chosenStatements!.length > 1 ? ' of these statements' : ' of this statement') : ''}?`}
        confirmLabel={`Post ${bulk.count}`}
        onConfirm={() => post(scopedHigh ? { classifications: scopedHigh.map((r) => r.id) } : { band: 'HIGH' })}
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
        open={!!confirmGroup}
        onOpenChange={(open) => !open && setConfirmGroup(null)}
        title={confirmGroup ? `Post ${plural(confirmGroup.rows.length, 'row')} like “${confirmGroup.label}”?` : ''}
        confirmLabel={confirmGroup ? `Post ${confirmGroup.rows.length}` : 'Post'}
        onConfirm={async () => {
          if (confirmGroup) await post({ classifications: confirmGroup.rows.map((r) => r.id) })
        }}
      >
        {confirmGroup && (
          <>
            <p>
              {confirmGroup.debit ? 'Paid out' : 'Received'} {formatPaise(confirmGroup.totalPaise)} in all, every row placed in <b>{confirmGroup.ledgerName}</b>.
            </p>
            {confirmGroup.byModel > 0 && <p>{plural(confirmGroup.byModel, 'row')} were placed by the assistant from the narration: a guess. Open the group first if you have not looked at them.</p>}
            <p>Each becomes a journal entry in the Day Book. All are posted together, or none.</p>
          </>
        )}
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

function SortChip({ label, sortKey, sort, onSort }: { label: string; sortKey: SortKey; sort: Sort; onSort: (key: SortKey) => void }) {
  const on = sort?.key === sortKey
  const flipped = on && sort.dir === 'desc'
  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      aria-pressed={on}
      title={sortKey === 'amount' ? 'Sort by amount (withdrawals and deposits together)' : `Sort by ${label.toLowerCase()}`}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-3 py-0.5 text-[13px] transition-colors duration-200',
        on ? 'border-foreground bg-foreground text-background' : 'hover:bg-hover',
      )}
    >
      {label}
      <ArrowUp className={cn('size-3 transition-[rotate,opacity] duration-200', flipped && 'rotate-180', !on && 'opacity-40')} aria-hidden />
    </button>
  )
}

const NEW_PARTY = '__new__'

/** Inline, the less used fields (party, TDS, reverse charge) are folded away; on the side panel they are simply shown. */
function Folded({ flat, open, children }: { flat?: boolean; open: boolean; children: React.ReactNode }) {
  if (!flat) return <>{children}</>
  return (
    <details open={open || undefined} className="border-t border-border-strong pt-3">
      <summary className="cursor-pointer text-sm text-muted-foreground">Party, TDS and reverse charge</summary>
      <div className="mt-3 grid gap-3">{children}</div>
    </details>
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
  /** Inline under its row: no card of its own, no sticky positioning. */
  flat?: boolean
  onDone: () => void
}) {
  const { can } = useSession()
  const parties = useQuery(partiesQuery(clientId))
  const invalidate = useInvalidateClient(clientId)
  const queryClient = useQueryClient()
  const ledgerInput = useRef<HTMLInputElement>(null)
  const suggested = ledgers.some((l) => l.id === row.ledger) ? row.ledger : null
  const proposal = allLedgers.find((l) => l.id === row.ledger && (l.status === 'PROPOSED' || l.awaiting_look)) ?? null
  const [deciding, setDeciding] = useState(false)
  const [openingIdea, setOpeningIdea] = useState(false)
  const [newParty, setNewParty] = useState<{ name: string; gstin: string; error: string | null; busy: boolean } | null>(null)

  async function createParty() {
    if (!newParty) return
    setNewParty({ ...newParty, busy: true, error: null })
    try {
      const made = await raw.post<Party>(`${V1}/clients/${clientId}/parties/`, {
        canonical_name: newParty.name.trim(),
        role: row.transaction.is_debit ? 'VENDOR' : 'CUSTOMER',
        gstin: newParty.gstin.trim(),
      })
      await invalidate()
      setParty(made.id)
      setNewParty(null)
      toast.success(`${made.canonical_name} added`)
    } catch (e) {
      const fields = isApiError(e) ? e.fields : {}
      const message = fields.canonical_name?.[0] ?? fields.gstin?.[0] ?? messageOf(e)
      setNewParty((current) => (current ? { ...current, busy: false, error: message } : current))
    }
  }
  const [ledger, setLedger] = useState<string | null>(suggested)
  const [party, setParty] = useState<string>(row.party ?? '')
  const [tds, setTds] = useState<string>(row.tds_section ?? '')
  const [rcm, setRcm] = useState(row.rcm)
  const [learn, setLearn] = useState(!row.is_self_transfer && !!row.counterparty)
  // Which action is waiting on the server: only that button spins, and the others wait their turn.
  const [action, setAction] = useState<'place' | 'post' | 'party' | null>(null)
  const busy = action !== null
  const t = row.transaction
  const canPlace = can('transaction.classify')
  const mayUndoRule = can('suggestion.edit')
  const unchanged = ledger === row.ledger && (party || null) === (row.party ?? null) && tds === (row.tds_section ?? '') && rcm === row.rcm
  const alreadyPlacedByPerson = row.method === 'REVIEWED' && unchanged

  function place() {
    if (!ledger) return ledgerInput.current?.focus()
    return placeIn(ledger)
  }

  /** Place the row in ``chosen``. Takes the ledger as an argument, so a ledger created a moment ago is not lost to stale state. */
  async function placeIn(chosen: string) {
    setAction('place')
    try {
      const result = await raw.post<PlacementResult>(`${V1}/classifications/${row.id}/review/`, {
        ledger: chosen,
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
      setAction(null)
    }
  }

  async function postNow() {
    setAction('post')
    try {
      await raw.post(`${V1}/clients/${clientId}/approvals/`, { classifications: [row.id] })
      await invalidate()
      toast.success('Posted to the Day Book')
      onDone()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setAction(null)
    }
  }

  async function confirmParty(id: string) {
    setAction('party')
    try {
      await raw.post(`${V1}/classifications/${row.id}/confirm-party/`, { party: id })
      await invalidate()
      setParty(id)
      toast.success('Payee confirmed', { description: 'Every other waiting row with this spelling is now recognised too.' })
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setAction(null)
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
    <Card className={cn('grid content-start gap-4 p-4', flat ? 'border-0 bg-transparent p-0 shadow-none' : 'xl:sticky xl:top-20 xl:max-h-[calc(100svh-6rem)] xl:overflow-auto xl:overscroll-contain')}>
      <div className="grid content-start gap-4">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <span className={cn('num text-muted-foreground', flat ? 'font-mono text-[13px]' : 'text-sm')}>{formatDate(t.value_date)}</span>
          <span className={cn('num font-semibold', flat ? 'font-mono text-[26px] leading-tight' : 'text-lg', t.is_debit ? 'text-foreground' : 'text-success')}>
            {t.is_debit ? 'Paid ' : 'Received '}
            {t.amount_display}
          </span>
        </div>
        <p className={cn('mt-1 break-words font-mono', flat ? 'text-xs text-muted-foreground' : 'text-[13px]')}>{t.narration}</p>
        {((row.channel && row.channel !== 'UNKNOWN') || row.counterparty || row.is_self_transfer) && (
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
            {row.channel && row.channel !== 'UNKNOWN' && <Badge>{row.channel}</Badge>}
            {row.counterparty && <Badge tone="outline">{row.counterparty}</Badge>}
            {row.is_self_transfer && <Badge tone="info">Between the client’s own accounts</Badge>}
          </div>
        )}
      </div>

      {row.open_question && (
        <div className={cn('flex gap-2 border border-accent-edge bg-accent text-sm', flat ? 'rounded-lg px-3.5 py-3' : 'rounded-md p-2.5')}>
          {!flat && <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />}
          <span>{row.open_question}</span>
        </div>
      )}

      {row.suggested_ledger && canPlace && (
        <LedgerIdea
          suggestion={row.suggested_ledger}
          placedIn={row.ledger_name ?? null}
          canCreate={can('ledger.manage')}
          busy={busy}
          onPlaceExisting={(id) => void placeIn(id)}
          onCreate={() => setOpeningIdea(true)}
        />
      )}
      {openingIdea && row.suggested_ledger && (
        <NewAccountDialog
          clientId={clientId}
          ledgers={ledgers}
          initialName={row.suggested_ledger.name}
          initialGroup={row.suggested_ledger.group}
          onCreated={(made) => {
            setOpeningIdea(false)
            setLedger(made.id)
            void placeIn(made.id)
          }}
          onClose={() => setOpeningIdea(false)}
        />
      )}

      {legs.length > 0 && (
        <div>
          <div className={cn('mb-1.5 text-[13px]', flat ? 'text-muted-foreground' : 'font-medium')}>The entry this makes</div>
          <div className={flat ? 'rounded-lg border border-border-strong px-4' : undefined}>
            <table className="w-full text-sm">
              <tbody>
                {legs.map((leg, i) => (
                  <tr key={i} className={cn('border-b last:border-b-0', flat && 'border-border-strong')}>
                    <td className={cn('w-8 text-muted-foreground', flat ? 'py-2.5' : 'py-1')}>{leg.side}</td>
                    <td className={flat ? 'py-2.5' : 'py-1'}>{leg.ledger ?? <span className="italic text-muted-foreground">choose a ledger</span>}</td>
                    <td className={cn('num text-right', flat ? 'py-2.5 font-mono' : 'py-1')}>
                      <Money display={leg.amount_display} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {extras && <p className="mt-1 text-xs text-muted-foreground">{extras}</p>}
          {ledger !== row.ledger && ledger && <p className="mt-1 text-xs text-info">Not saved yet: press Enter or Place in ledger.</p>}
        </div>
      )}

      {row.ledger && row.method !== 'REVIEWED' && (
        <div className="grid gap-1 rounded-md border border-info/30 bg-info-bg px-3 py-2 text-[13px]">
          <div className="flex items-center gap-1.5 font-medium text-foreground">
            {row.memory ? <MemoryIcon kind={row.memory.kind} className="size-4 text-info" /> : null}
            {row.memory?.label ?? row.method_display}
            <span className="font-normal text-muted-foreground">{row.confidence ? ` · ${Math.round(row.confidence * 100)}% sure` : ''}</span>
          </div>
          <p className="text-muted-foreground">{row.memory?.note ?? row.rationale}</p>
          {row.memory?.kind === 'rule' && (
            <p className="text-xs text-muted-foreground">Wrong? Place it in the right ledger below and tick “also place future…” to teach it the correct one.</p>
          )}
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
      </div>

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

          <Folded flat={flat} open={!!newParty || (row.party_candidates?.length > 0 && !row.party)}>
          <div className="grid gap-1.5">
            <label className="text-[13px] font-medium" htmlFor={`party-${row.id}`}>
              Party (who it was paid to or received from)
            </label>
            {row.party_candidates?.length > 0 && !row.party && (
              <div className="flex flex-wrap gap-1.5">
                {row.party_candidates.slice(0, 3).map((c) => (
                  <Button key={c.party} size="sm" variant="outline" onClick={() => void confirmParty(c.party)} disabled={busy} title={c.why}>
                    Is it {c.name}?
                  </Button>
                ))}
              </div>
            )}
            <Select
              id={`party-${row.id}`}
              value={newParty ? NEW_PARTY : party}
              onChange={(e) => {
                if (e.target.value === NEW_PARTY) setNewParty({ name: row.counterparty ?? '', gstin: '', error: null, busy: false })
                else {
                  setNewParty(null)
                  setParty(e.target.value)
                }
              }}
            >
              <option value="">No party</option>
              {(parties.data ?? [])
                .filter((p) => p.is_active !== false)
                .map((p) => (
                  <option key={p.id} value={p.id}>{p.canonical_name}</option>
                ))}
              {can('party.manage') && <option value={NEW_PARTY}>+ Add a new party…</option>}
            </Select>
            {newParty && (
              <fieldset className="grid gap-2 rounded-md border bg-muted/40 p-3">
                <div className="text-[13px] font-medium">New {t.is_debit ? 'supplier' : 'customer'}</div>
                <Input aria-label="New party name" autoFocus placeholder="Name" value={newParty.name} onChange={(e) => setNewParty({ ...newParty, name: e.target.value, error: null })} />
                <Input
                  aria-label="New party GSTIN"
                  placeholder="GSTIN (leave blank if unregistered)"
                  value={newParty.gstin}
                  onChange={(e) => setNewParty({ ...newParty, gstin: e.target.value.toUpperCase(), error: null })}
                />
                {newParty.error && <p role="alert" className="text-xs text-destructive">{newParty.error}</p>}
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setNewParty(null)}>Cancel</Button>
                  <Button size="sm" loading={newParty.busy} disabled={newParty.name.trim().length < 2} onClick={() => void createParty()}>
                    {newParty.busy ? 'Adding…' : 'Add and use'}
                  </Button>
                </div>
              </fieldset>
            )}
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
          </Folded>

          {canPost && row.ledger && unchanged && row.on_party_account && (
            <SettlementPanel clientId={clientId} row={row} onDone={onDone} />
          )}

          <div className={cn('flex flex-wrap items-center gap-2 max-sm:[&>*]:flex-1', flat ? 'justify-between pt-1' : 'sticky bottom-0 -mx-4 justify-end border-t bg-card px-4 py-3')}>
            {flat && (
              <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground max-sm:hidden">
                <Kbd className="border-border-strong bg-background">L</Kbd> ledger · <Kbd className="border-border-strong bg-background">Enter</Kbd> place
              </span>
            )}
            <span className="flex flex-wrap items-center justify-end gap-2 max-sm:w-full max-sm:[&>*]:flex-1">
            {!alreadyPlacedByPerson && (
              <Button variant={row.ledger && unchanged ? 'outline' : 'primary'} onClick={() => void place()} loading={action === 'place'} disabled={busy}>
                {row.ledger && ledger === row.ledger ? 'Confirm ledger' : 'Place in ledger'} <Kbd className={cn('ml-1 max-sm:hidden', row.ledger && unchanged ? 'border-border-strong bg-transparent' : 'border-primary-foreground/30 bg-transparent text-primary-foreground/80')}>Enter</Kbd>
              </Button>
            )}
            {canPost && row.ledger && unchanged && !row.on_party_account && (
              <Button onClick={() => void postNow()} loading={action === 'post'} disabled={busy}>
                Post entry <Kbd className="ml-1 bg-transparent text-primary-foreground/80 max-sm:hidden">P</Kbd>
              </Button>
            )}
            </span>
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


/** Where a placement came from: a rule the system learned from a person, an invoice it matched, or the AI's own guess. */
function MemoryIcon({ kind, className }: { kind: 'rule' | 'matched' | 'ai'; className?: string }) {
  const Icon = kind === 'rule' ? Brain : kind === 'matched' ? Link2 : Sparkles
  return <Icon className={className} aria-hidden />
}
