// The Day Book: every posted voucher for the year, in date order, the way Tally lists it.
//
// Date, Particulars, Vch Type, Vch No., Debit, Credit. Particulars is the ledger on the other
// side from the bank, which is what a CA scans for. Entries the rules posted with nobody
// looking carry a marker until someone has; entries inside signed-off books carry a lock.
// Opening one shows both sides, who posted it, what it used to be, and -- while the books are
// a draft -- lets you correct or remove it.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Lock, Search, Undo2 } from 'lucide-react'
import { useMemo, useState } from 'react'
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
import { Checkbox, Textarea } from '@/components/ui/controls'
import { DataTable, type Column } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { LedgerPicker, usableLedgers } from '@/features/review/LedgerPicker'
import { formatDate, formatDateTime, formatPaise, fyLabel, plural } from '@/lib/format'
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
  const [open, setOpen] = useState<JournalEntry | null>(null)

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
  type Row = (typeof rows)[number]
  const dash = <span className="text-faint" aria-hidden>–</span>
  const columns: Column<Row>[] = [
    { key: 'date', header: 'Date', align: 'right', cell: ({ e }) => formatDate(e.entry_date) },
    {
      key: 'particulars',
      header: 'Particulars',
      className: 'max-w-0 w-full',
      cell: ({ e, line }) => (
        <>
          <span className="flex items-center gap-1.5">
            <span className="truncate font-medium text-heading">{line.ledger_name}</span>
            {line.party_name && <span className="truncate text-muted-foreground">· {line.party_name}</span>}
            {e.marker && <Badge tone="assistant">{e.marker === 'AI_POSTED' ? 'Assistant posted' : 'Assistant changed'}</Badge>}
            {e.is_locked && <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-label="Sealed" />}
          </span>
          <div className="truncate text-xs text-muted-foreground" title={e.narration}>
            {e.narration}
          </div>
        </>
      ),
    },
    { key: 'type', header: 'Vch type', priority: 2, cell: ({ e }) => e.voucher_type },
    { key: 'no', header: 'Vch no.', priority: 2, align: 'right', cell: ({ e }) => e.entry_no },
    { key: 'debit', header: 'Debit', align: 'right', cell: ({ line, isDr }) => (isDr ? <Money display={line.amount_display} /> : dash) },
    { key: 'credit', header: 'Credit', align: 'right', cell: ({ line, isDr }) => (!isDr ? <Money display={line.amount_display} /> : dash) },
  ]
  const mayUnpost = can('journal.approve') && !!client.data?.can_post
  const assistantEntries = inYear.filter(isAssistantEntry)
  return (
    <div className="grid gap-3 [&>*]:min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">
          FY {fyLabel(fy)} · {plural(inYear.length, 'voucher')}
          {otherYears > 0 && ` · ${otherYears} in other years (change the year at the top)`}
        </div>
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input aria-label="Search the Day Book" placeholder="Ledger, party or narration" className="w-60 pl-8" value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          <div className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1 text-sm [scrollbar-width:none]">
            {['', ...TYPES].map((t) => (
              <button
                key={t || 'all'}
                type="button"
                onClick={() => setType(t)}
                aria-pressed={type === t}
                className={cn('shrink-0 whitespace-nowrap rounded-md px-2.5 py-1 text-muted-foreground max-sm:min-h-10', type === t && 'bg-card text-foreground shadow-xs')}
              >
                {t || 'All'}
              </button>
            ))}
          </div>
          <Checkbox label="Assistant entries only" checked={onlyAi} onChange={(e) => setOnlyAi(e.target.checked)} />
          {mayUnpost && assistantEntries.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => setBulk(true)}>
              <Undo2 /> Unpost {assistantEntries.length} assistant-posted
            </Button>
          )}
        </div>
      </div>

      <DataTable
        caption={`Day Book, FY ${fyLabel(fy)}`}
        columns={columns}
        rows={rows}
        loading={entries.isPending || accounts.isPending}
        rowKey={(r) => r.e.id}
        onRowClick={(r) => setOpen(r.e)}
        scrollHeight="calc(100svh - 17rem)"
        empty={
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
        }
        footer={
          <tr>
            <td className="px-3 py-2" colSpan={4}>
              Total ({plural(shown.length, 'voucher')})
            </td>
            <td className="num px-3 py-2 text-right">{formatPaise(debit)}</td>
            <td className="num px-3 py-2 text-right">{formatPaise(credit)}</td>
          </tr>
        }
      />

      {open && <EntryDialog clientId={clientId} entry={open} onClose={() => setOpen(null)} />}

      <Confirm
        open={bulk}
        onOpenChange={setBulk}
        title={`Unpost ${plural(assistantEntries.length, 'assistant-posted entry', 'assistant-posted entries')}?`}
        confirmLabel={`Unpost ${assistantEntries.length}`}
        note="optional"
        noteLabel="Why (kept in each entry's change log)"
        onConfirm={async (note) => {
          const { done, failed } = await unpostMany(assistantEntries, note || 'Unposted: posted by the assistant without review.')
          if (failed.length) toast.warning(`Unposted ${done}; ${failed.length} could not be`, { description: failed.slice(0, 3).join(' · ') })
          else toast.success(`Unposted ${plural(done, 'entry', 'entries')}; the transactions are back in Review`)
        }}
      >
        <p>
          Every entry in FY {fyLabel(fy)} that rules posted without a person looking leaves the books, and its transaction goes back to
          Review to be decided. What each entry was is kept in its change log. Entries you have already corrected are not included.
        </p>
      </Confirm>
    </div>
  )
}

function EntryDialog({ clientId, entry, onClose }: { clientId: string; entry: JournalEntry; onClose: () => void }) {
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

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="sm:left-auto sm:right-0 sm:top-0 sm:h-svh sm:max-h-none sm:w-full sm:max-w-xl sm:translate-x-0 sm:translate-y-0 sm:content-start sm:rounded-none sm:border-y-0 sm:border-r-0"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>
            {entry.voucher_type} No. {entry.entry_no} · {formatDate(entry.entry_date)}
          </DialogTitle>
          <DialogDescription>
            FY {entry.fy_label}
            {entry.approved_by_email ? ` · Posted by ${entry.approved_by_email}, ${formatDateTime(entry.approved_at)}` : ' · Posted automatically by a rule'}
            {entry.is_locked && ' · In signed-off books'}
          </DialogDescription>
        </DialogHeader>

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
        <p className="text-sm">
          <span className="text-muted-foreground">Narration: </span>
          {entry.narration}
        </p>
        {entry.marker && (
          <p className="rounded-md bg-info-bg p-2.5 text-sm">
            {entry.marker === 'AI_POSTED'
              ? 'Posted by a rule without anyone looking. If it is wrong, unpost it below and decide it in Review; if it is right, clear the marker on the Books tab.'
              : 'Changed by the assistant after a correction elsewhere. Check it.'}
          </p>
        )}

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
          mayEdit && (
            <div className="flex justify-end gap-2">
              {!entry.is_locked && (
                <Button variant="outline" onClick={() => setRemoving(true)}>
                  <Undo2 /> Unpost (back to Review)
                </Button>
              )}
              <Button onClick={() => setCorrecting(true)}>Correct</Button>
            </div>
          )
          )
        )}

        <div>
          <div className="mb-1 text-[13px] font-medium">History</div>
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
      </DialogContent>
    </Dialog>
  )
}
