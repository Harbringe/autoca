// The Day Book: every posted voucher for the year, in date order, the way Tally lists it.
//
// Date, Particulars, Vch Type, Vch No., Debit, Credit. Particulars is the ledger on the other
// side from the bank, which is what a CA scans for. Entries the rules posted with nobody
// looking carry a marker until someone has; entries inside signed-off books carry a lock.
// Opening one shows both sides, who posted it, what it used to be, and -- while the books are
// a draft -- lets you correct or remove it.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Check, ChevronRight, Lock, Search, Undo2 } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { entryChanges, journal, ledgers as ledgersQuery } from '@/api/queries/books'
import { bankAccounts, clientDetail, clientKeys, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { JournalEntry } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapse, useClosing } from '@/components/ui/collapse'
import { GlideChips } from '@/components/ui/glide-chips'
import { Checkbox, Textarea } from '@/components/ui/controls'
import { DataTable } from '@/components/ui/table'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { LedgerPicker, usableLedgers } from '@/features/review/LedgerPicker'
import { formatDate, formatDateTime, formatPaise, fyLabel, parseRupees, plural } from '@/lib/format'
import { useFy } from '@/features/shell/useFy'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { isAssistantEntry, unpostEntry, useUnpostMany } from './unpost'

const TYPES = ['Payment', 'Receipt', 'Contra', 'Journal', 'Purchase', 'Sales', 'Debit Note', 'Credit Note'] as const

/** The line a Day Book shows as Particulars: the side that is not this client's bank. */
function particulars(entry: JournalEntry, bankNames: Set<string>) {
  // A purchase or sales voucher has no bank on either side: what a CA scans for is who it is with.
  const party = entry.entry_kind !== 'BANK' ? entry.lines.find((l) => l.party_name) : undefined
  if (party) return party
  const other = entry.lines.filter((l) => !bankNames.has(l.ledger_name))
  const line = other[other.length - 1] ?? entry.lines[0]
  return line
}

export function DayBookScreen({ clientId }: { clientId: string }) {
  const { fy } = useFy()
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const unpostMany = useUnpostMany(clientId)
  const [bulk, setBulk] = useState(false)
  const entries = useQuery(journal(clientId))
  const accounts = useQuery(bankAccounts(clientId))
  const [type, setType] = useState<string>('')
  const [text, setText] = useState('')
  const [onlyAi, setOnlyAi] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const closingId = useClosing(openId)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [marking, setMarking] = useState(false)
  const invalidate = useInvalidateClient(clientId)
  const queryClient = useQueryClient()

  const bankNames = useMemo(() => new Set((accounts.data?.results ?? []).map((a) => a.ledger_name ?? '')), [accounts.data])
  const inYear = useMemo(() => (entries.data ?? []).filter((e) => e.financial_year === fy), [entries.data, fy])
  const shown = useMemo(() => {
    const q = text.trim().toLowerCase()
    return inYear
      .filter((e) => !type || e.voucher_type === type)
      .filter((e) => !onlyAi || !!e.marker)
      .filter((e) => !q || e.narration.toLowerCase().includes(q) || e.lines.some((l) => l.ledger_name.toLowerCase().includes(q) || (l.party_name ?? '').toLowerCase().includes(q)))
      .sort((a, b) => a.entry_date.localeCompare(b.entry_date) || a.voucher_type.localeCompare(b.voucher_type) || a.entry_no - b.entry_no)
  }, [inYear, type, text, onlyAi])

  let debit = 0
  let credit = 0
  const rows = shown.map((e) => {
    const line = particulars(e, bankNames)!
    const isDr = line.direction === 'DR'
    if (isDr) debit += line.amount_paise
    else credit += line.amount_paise
    return { e, line, isDr }
  })

  if (entries.error) return <ErrorState error={entries.error} retry={() => void entries.refetch()} />

  const otherYears = (entries.data ?? []).length - inYear.length
  const mayUnpost = can('journal.approve') && !!client.data?.can_post
  const mayMark = can('journal.correct') && !!client.data?.can_post
  const assistantEntries = inYear.filter(isAssistantEntry)
  const selectable = mayMark || mayUnpost ? shown.filter(isAssistantEntry) : []
  const chosen = selectable.filter((e) => picked.has(e.id))
  // With some ticked, the buttons act on those; with none, on every assistant entry of the year.
  const targets = chosen.length ? chosen : assistantEntries
  const targetWord = chosen.length ? 'selected' : 'assistant-posted'
  const withBox = selectable.length > 0
  const columnCount = 6 + (withBox ? 1 : 0)
  const allPicked = selectable.length > 0 && chosen.length === selectable.length
  const toggle = (id: string) =>
    setPicked((was) => {
      const next = new Set(was)
      if (!next.delete(id)) next.add(id)
      return next
    })

  async function markChecked(list: JournalEntry[]) {
    setMarking(true)
    try {
      const ids = list.map((e) => e.id)
      for (let i = 0; i < ids.length; i += 500) await raw.post(`${V1}/clients/${clientId}/books/mark-reviewed/`, { entries: ids.slice(i, i + 500) })
      await Promise.all([invalidate(), queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'journal') })])
      setPicked(new Set())
      toast.success(list.length === 1 ? 'Marked as checked' : `${plural(list.length, 'entry', 'entries')} marked as checked`)
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setMarking(false)
    }
  }

  const numCell = 'num px-4 py-4 text-right align-top'
  const dash = <span className="text-faint" aria-hidden>–</span>
  const headCell = 'whitespace-nowrap px-4 py-4 text-xs font-semibold text-muted-foreground'
  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          FY {fyLabel(fy)} · {plural(inYear.length, 'voucher')}
          {otherYears > 0 && ` · ${otherYears} in other years (change the year at the top)`}
        </div>
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input aria-label="Search the Day Book" placeholder="Ledger, party or narration" className="w-64 pl-8" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <Checkbox label="Assistant entries only" checked={onlyAi} onChange={(e) => setOnlyAi(e.target.checked)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <GlideChips
          label="Voucher type"
          value={type}
          onChange={setType}
          options={['', ...TYPES].map((t) => ({ value: t, label: t || 'All' }))}
        />
        {targets.length > 0 && (mayMark || mayUnpost) && (
          <div className="flex flex-wrap items-center gap-2">
            {mayMark && (
              <Button variant="outline" size="sm" disabled={marking} onClick={() => void markChecked(targets)}>
                <Check /> Mark {targets.length} {targetWord} as checked
              </Button>
            )}
            {mayUnpost && (
              <Button variant="outline" size="sm" onClick={() => setBulk(true)}>
                <Undo2 /> Unpost {targets.length} {targetWord}
              </Button>
            )}
          </div>
        )}
      </div>

      {entries.isPending || accounts.isPending ? (
        <Spinner label="Reading the Day Book…" />
      ) : rows.length === 0 ? (
        inYear.length === 0 ? (
          <EmptyState title={`No vouchers in FY ${fyLabel(fy)}`}>
            Post rows from{' '}
            <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="underline">
              Review
            </Link>
            {otherYears > 0 ? `, or pick another financial year at the top (${otherYears} entries are in other years).` : '.'}
          </EmptyState>
        ) : (
          <EmptyState title="No voucher matches">
            <button type="button" className="underline" onClick={() => { setText(''); setType(''); setOnlyAi(false) }}>
              Clear the filters
            </button>
          </EmptyState>
        )
      ) : (
        <div role="region" aria-label={`Day Book, FY ${fyLabel(fy)}`} className="overflow-x-auto rounded-xl border border-border-strong bg-card">
          <table className="w-full text-left text-sm max-sm:table-fixed">
            <caption className="sr-only">Day Book, FY {fyLabel(fy)}. Select a voucher to open it.</caption>
            <thead className="border-b border-border-strong">
              <tr>
                {withBox && (
                  <th scope="col" className="w-12 py-4 pl-4 pr-0 align-middle sm:pl-5">
                    <Checkbox
                      aria-label="Select every assistant entry shown"
                      checked={allPicked}
                      onChange={() => setPicked(allPicked ? new Set() : new Set(selectable.map((e) => e.id)))}
                    />
                  </th>
                )}
                <th scope="col" className={cn(headCell, 'max-sm:hidden')}>Date</th>
                <th scope="col" className={cn(headCell, 'w-full')}>Particulars</th>
                <th scope="col" className={cn(headCell, 'max-sm:hidden')}>Vch type</th>
                <th scope="col" className={cn(headCell, 'text-right max-sm:hidden')}>Vch no.</th>
                <th scope="col" className={cn(headCell, 'w-32 text-right sm:hidden')}>Amount</th>
                <th scope="col" className={cn(headCell, 'text-right max-sm:hidden')}>Debit</th>
                <th scope="col" className={cn(headCell, 'text-right max-sm:hidden')}>Credit</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ e, line, isDr }) => {
                const isOpen = openId === e.id
                const detailShown = isOpen || closingId === e.id
                const toggleOpen = () => setOpenId(isOpen ? null : e.id)
                return (
                  <Fragment key={e.id}>
                    <tr
                      onClick={(ev) => {
                        if ((ev.target as HTMLElement).closest('a, button, input, label')) return
                        toggleOpen()
                      }}
                      className={cn('cursor-pointer border-b border-border-strong hover:bg-hover', isOpen && 'bg-surface-2', !detailShown && 'last:border-b-0')}
                    >
                      {withBox && (
                        <td className="w-12 py-4 pl-4 pr-0 align-top sm:pl-5">
                          {isAssistantEntry(e) && <Checkbox aria-label={`Select ${e.voucher_type} ${e.entry_no}`} checked={picked.has(e.id)} onChange={() => toggle(e.id)} />}
                        </td>
                      )}
                      <td className="num whitespace-nowrap px-4 py-4 align-top font-medium text-heading max-sm:hidden">{formatDate(e.entry_date)}</td>
                      <td className="w-full max-w-0 px-4 py-4 align-top">
                        <button
                          type="button"
                          onClick={toggleOpen}
                          aria-expanded={isOpen}
                          className="flex w-full min-w-0 flex-col gap-1 rounded-sm text-left focus-visible:outline-offset-4"
                        >
                          <span className="num pl-[22px] text-xs font-medium text-heading sm:hidden">{formatDate(e.entry_date)}</span>
                          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <ChevronRight aria-hidden className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform duration-200', isOpen && 'rotate-90')} />
                            <span className="truncate font-medium text-heading">{line.ledger_name}</span>
                            {line.party_name && <span className="truncate text-muted-foreground">· {line.party_name}</span>}
                            {e.marker && <Badge tone="assistant">{e.marker === 'AI_POSTED' ? 'Assistant posted' : 'Assistant changed'}</Badge>}
                            {e.is_locked && <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-label="Sealed" />}
                          </span>
                          {!isOpen && (
                            <span className="line-clamp-2 pl-[22px] text-[13px] leading-snug text-muted-foreground" title={e.narration}>
                              {e.narration}
                            </span>
                          )}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-4 align-top text-muted-foreground max-sm:hidden">{e.voucher_type}</td>
                      <td className={cn(numCell, 'max-sm:hidden')}>{e.entry_no}</td>
                      <td className={cn(numCell, 'sm:hidden')}>
                        <Money display={line.amount_display} />
                        <div className="text-xs font-normal text-muted-foreground">{isDr ? 'Dr' : 'Cr'}</div>
                      </td>
                      <td className={cn(numCell, 'max-sm:hidden')}>{isDr ? <Money display={line.amount_display} /> : dash}</td>
                      <td className={cn(numCell, 'max-sm:hidden')}>{!isDr ? <Money display={line.amount_display} /> : dash}</td>
                    </tr>
                    {detailShown && (
                      <tr className="border-b border-border-strong bg-surface-2 last:border-b-0">
                        <td colSpan={columnCount} className="max-w-0 overflow-hidden p-0">
                          <Collapse open={isOpen}>
                            <EntryDetail clientId={clientId} entry={e} onClose={() => setOpenId(null)} onMark={() => markChecked([e])} marking={marking} />
                          </Collapse>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
            <tfoot className="border-t-2 border-foreground bg-surface-2 font-semibold">
              <tr>
                <td className="px-4 py-4 max-sm:hidden" colSpan={columnCount - 2}>
                  Total ({plural(shown.length, 'voucher')})
                </td>
                <td className="px-4 py-4 sm:hidden" colSpan={withBox ? 2 : 1}>
                  Total ({plural(shown.length, 'voucher')})
                </td>
                <td className="num px-4 py-4 text-right max-sm:hidden">{formatPaise(debit)}</td>
                <td className="num px-4 py-4 text-right max-sm:hidden">{formatPaise(credit)}</td>
                <td className="px-4 py-4 text-right text-xs font-normal text-muted-foreground sm:hidden">Dr {formatPaise(debit)}<br />Cr {formatPaise(credit)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <Confirm
        open={bulk}
        onOpenChange={setBulk}
        title={`Unpost ${plural(targets.length, 'assistant-posted entry', 'assistant-posted entries')}?`}
        confirmLabel={`Unpost ${targets.length}`}
        note="optional"
        noteLabel="Why (kept in each entry's change log)"
        onConfirm={async (note) => {
          const { done, failed } = await unpostMany(targets, note || 'Unposted: posted by the assistant without review.')
          setPicked(new Set())
          if (failed.length) toast.warning(`Unposted ${done}; ${failed.length} could not be`, { description: failed.slice(0, 3).join(' · ') })
          else toast.success(`Unposted ${plural(done, 'entry', 'entries')}; the transactions are back in Review`)
        }}
      >
        <p>
          {chosen.length ? 'The entries you ticked' : `Every entry in FY ${fyLabel(fy)} that rules posted without a person looking`} leave the books, and each
          transaction goes back to Review to be decided. What each entry was is kept in its change log. Entries you have already corrected are not included.
        </p>
      </Confirm>
    </div>
  )
}

/** An opened voucher, laid out in one column under its row: what it is, both sides, who posted it, what to do next. */
function EntryDetail({
  clientId,
  entry,
  onClose,
  onMark,
  marking,
}: {
  clientId: string
  entry: JournalEntry
  onClose: () => void
  onMark: () => void
  marking: boolean
}) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const queryClient = useQueryClient()
  const [gone, setGone] = useState(false)
  const changes = useQuery({ ...entryChanges(clientId, entry.id), enabled: !gone })
  const ledgers = useQuery(ledgersQuery(clientId))
  const accounts = useQuery(bankAccounts(clientId))
  const invalidate = useInvalidateClient(clientId)
  const [correcting, setCorrecting] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [rectifying, setRectifying] = useState(false)
  const [fromLedger, setFromLedger] = useState<string>(entry.lines[0]?.ledger_account ?? '')
  const [toLedger, setToLedger] = useState<string | null>(null)
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [rectDate, setRectDate] = useState(new Date().toISOString().slice(0, 10))

  const bankNames = new Set((accounts.data?.results ?? []).map((a) => a.ledger_name ?? ''))
  const sourceBank = entry.lines.find((l) => bankNames.has(l.ledger_name))?.ledger_name
  const other = particulars(entry, bankNames)
  const [ledger, setLedger] = useState<string | null>(other?.ledger_account ?? null)
  const [narration, setNarration] = useState(entry.narration)
  const [onlyThis, setOnlyThis] = useState(true)
  const navigate = useNavigate()
  // A purchase, sales or note voucher has no bank row, so it is changed through its bill, not by the bank-entry correction.
  const isVoucher = entry.entry_kind !== 'BANK'
  const mayEdit = !isVoucher && can('journal.correct') && !!client.data?.can_post && (!entry.is_locked || !!client.data?.can_sign_off)

  const mayRectify = entry.is_locked && can('journal.correct') && !!client.data?.can_sign_off

  async function rectify() {
    const paise = parseRupees(amount)
    if (!paise || paise <= 0 || !toLedger) return
    try {
      await raw.post(`${V1}/journal-entries/${entry.id}/rectify/`, {
        from_ledger: fromLedger, to_ledger: toLedger, amount_paise: paise, reason, date: rectDate,
      })
      await invalidate()
      toast.success('Rectifying journal posted; the original entry is unchanged')
      onClose()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function correct() {
    try {
      await raw.post(`${V1}/journal-entries/${entry.id}/correct/`, {
        treatment: { ledger, learn: !onlyThis },
        narration: narration !== entry.narration ? narration : undefined,
      })
      await invalidate()
      toast.success(entry.is_locked ? 'Correcting entry posted after the signed-off period' : 'Entry corrected; the old version is kept in its history')
      onClose()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  const total = entry.lines.filter((l) => l.direction === 'DR').reduce((sum, l) => sum + l.amount_paise, 0)
  const mayMark = !!entry.marker && !entry.is_locked && can('journal.correct') && !!client.data?.can_post

  return (
    <div className="grid gap-6 px-5 py-6 sm:pl-[3.75rem] sm:pr-6 [&>*]:min-w-0">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-12 [&>*]:min-w-0">
      <div className="grid content-start gap-5 [&>*]:min-w-0">
        <div className="grid gap-1">
          <div className="text-sm text-muted-foreground">
            {entry.voucher_type} No. {entry.entry_no} · {formatDate(entry.entry_date)} · FY {entry.fy_label}
            {entry.is_locked && ' · In signed-off books'}
          </div>
          <div className="num text-[26px] font-semibold leading-tight text-heading">{formatPaise(total)}</div>
          <div className="text-sm text-muted-foreground">
            {entry.approved_by_email ? `Posted by ${entry.approved_by_email}, ${formatDateTime(entry.approved_at)}` : 'Posted automatically by a rule'}
          </div>
        </div>
        <DataTable
          caption={`Lines of ${entry.voucher_type} No. ${entry.entry_no}`}
          rows={entry.lines}
          rowKey={(l) => String(l.id)}
          columns={[
            { key: 'side', header: <span className="sr-only">Dr or Cr</span>, cell: (l) => <span className="text-muted-foreground">{l.direction === 'DR' ? 'Dr' : 'Cr'}</span>, width: '2.5rem' },
            {
              key: 'particulars',
              header: 'Particulars',
              className: 'whitespace-normal',
              cell: (l) => (
                <>
                  {l.ledger_name}
                  {l.party_name && <span className="text-muted-foreground"> · {l.party_name}</span>}
                  {(l.tds_section || l.rcm) && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {l.tds_section && `TDS ${l.tds_section}`} {l.rcm && 'RCM'}
                    </span>
                  )}
                </>
              ),
            },
            { key: 'debit', header: 'Debit', align: 'right', cell: (l) => (l.direction === 'DR' ? <Money display={l.amount_display} /> : <span className="text-faint" aria-hidden>–</span>) },
            { key: 'credit', header: 'Credit', align: 'right', cell: (l) => (l.direction === 'CR' ? <Money display={l.amount_display} /> : <span className="text-faint" aria-hidden>–</span>) },
          ]}
        />
        <div className="grid gap-1 text-sm">
          <span className="text-muted-foreground">Narration</span>
          <span className="leading-relaxed">{entry.narration}</span>
        </div>
      </div>
      <div className="grid content-start gap-5 [&>*]:min-w-0">
        {entry.marker && (
          <p className="rounded-lg border bg-info-bg p-3.5 text-sm leading-relaxed">
            {entry.marker === 'AI_POSTED' ? (
              <>
                <strong className="font-semibold">Nobody has looked at this entry yet.</strong> A rule posted it, so the books cannot be signed off
                until it is checked. If it is right, mark it checked. If it is wrong, unpost it and decide it in Review.
              </>
            ) : (
              <>
                <strong className="font-semibold">The assistant changed this entry</strong> after a correction elsewhere. Check it, then mark it checked.
              </>
            )}
          </p>
        )}

        <div className="grid gap-1.5 text-sm">
          <div className="text-muted-foreground">History</div>
          {changes.isPending ? (
            <Spinner className="p-2" />
          ) : (changes.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No changes since it was posted.</p>
          ) : (
            <ul className="grid gap-1 text-sm">
              {changes.data!.map((c) => (
                <li key={c.id} className="flex justify-between gap-3">
                  <span>
                    {c.action_display}
                    {c.note && <span className="text-muted-foreground"> · {c.note}</span>}
                  </span>
                  <span className="shrink-0 text-muted-foreground">
                    {c.actor_email ?? 'the assistant'} · {formatDateTime(c.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>
      </div>

        {correcting ? (
          <div className="grid gap-3 rounded-md border p-3">
            <LedgerPicker
              clientId={clientId}
              ledgers={usableLedgers(ledgers.data, sourceBank)}
              value={ledger}
              onChange={setLedger}
              label="Move to ledger"
            />
            <div className="grid gap-1.5">
              <label className="text-[13px] font-medium" htmlFor="narration">Narration</label>
              <Textarea id="narration" value={narration} onChange={(e) => setNarration(e.target.value)} />
            </div>
            <Checkbox label="This entry only (do not change the rule for this payee)" checked={onlyThis} onChange={(e) => setOnlyThis(e.target.checked)} />
            {entry.is_locked && (
              <p className="text-sm text-warning">
                This entry is in signed-off books. It will not be changed; a correcting entry is posted after the signed-off date instead.
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCorrecting(false)}>Cancel</Button>
              <Button onClick={() => void correct()} disabled={!ledger}>Save correction</Button>
            </div>
          </div>
        ) : (
          isVoucher && entry.bill ? (
            <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>This is a {entry.voucher_type.toLowerCase()} voucher. It is changed through its bill.</span>
              <Button
                onClick={() => void navigate({ to: '/clients/$clientId/bills', params: { clientId }, search: { bill: entry.bill ?? undefined } })}
              >
                Open the bill
              </Button>
            </div>
          ) : (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
            <div>
              {mayEdit && !entry.is_locked && (
                <Button variant="outline" className="border-destructive/50 text-destructive" onClick={() => setRemoving(true)}>
                  <Undo2 /> Unpost (back to Review)
                </Button>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="ghost" onClick={onClose}>Close</Button>
              {mayEdit && <Button variant="outline" onClick={() => setCorrecting(true)}>Correct</Button>}
              {mayMark && (
                <Button onClick={onMark} disabled={marking}>
                  <Check /> It is right: mark as checked
                </Button>
              )}
            </div>
          </div>
          )
        )}

        {mayRectify && (
          rectifying ? (
            <div className="grid gap-3 rounded-md border p-3">
              <p className="text-sm text-muted-foreground">
                This entry is in signed-off books and will not be changed. A journal dated after the sign-off moves the amount to the right ledger.
              </p>
              <Field label="Move from">
                {(p) => (
                  <select {...p} className="h-9 rounded-md border bg-background px-2 text-sm" value={fromLedger} onChange={(e) => setFromLedger(e.target.value)}>
                    {entry.lines.map((l) => (
                      <option key={l.id} value={l.ledger_account}>{l.ledger_name} ({l.direction === 'DR' ? 'debit' : 'credit'} {formatPaise(l.amount_paise)})</option>
                    ))}
                  </select>
                )}
              </Field>
              <LedgerPicker clientId={clientId} ledgers={usableLedgers(ledgers.data, sourceBank)} value={toLedger} onChange={setToLedger} label="Move to ledger" />
              <Field label="Amount (₹)">{(p) => <Input {...p} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}</Field>
              <Field label="Date of the journal">{(p) => <DateInput {...p} value={rectDate} onChange={(e) => setRectDate(e.target.value)} />}</Field>
              <Field label="Why">{(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setRectifying(false)}>Cancel</Button>
                <Button onClick={() => void rectify()} disabled={!toLedger || !parseRupees(amount) || reason.trim().length < 5}>Post journal</Button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end">
              <Button variant="outline" onClick={() => setRectifying(true)}>Rectify by journal</Button>
            </div>
          )
        )}

        <Confirm
          open={removing}
          onOpenChange={setRemoving}
          title="Unpost this entry?"
          confirmLabel="Unpost"
          note="optional"
          noteLabel="Why (kept in the change log)"
          onConfirm={async (note) => {
            await unpostEntry(entry, note)
            setGone(true)
            onClose()
            // Refresh everything except this entry's own history: the entry is gone, and asking
            // for its history while the dialog is still on its way out would be refused.
            queryClient.removeQueries({ queryKey: clientKeys.part(clientId, 'journal', entry.id) })
            await queryClient.invalidateQueries({
              queryKey: clientKeys.one(clientId),
              predicate: (q) => !q.queryKey.includes(entry.id),
            })
            await queryClient.invalidateQueries({ queryKey: clientKeys.all })
            toast.success('Unposted; the transaction is back in Review to be decided')
          }}
        >
          <p>
            The entry leaves the books and its bank transaction goes back to Review, where you can place it in a different ledger and post
            it again. What the entry was is kept in its change log. Voucher numbers close up when the books are sealed.
          </p>
        </Confirm>
    </div>
  )
}
