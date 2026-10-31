// Import a client's history from Tally: choose the vouchers export, read the preview, post it, or take a posted import back.
//
// Nothing is posted by choosing the file. The preview says what would be written and, for each voucher it would not write, why.
// The client's ledgers must be in AutoCA first (a voucher naming a ledger that is not there is skipped and says so), and bank vouchers
// are not imported yet, so a run is partial books until they are; the notice says so in plain words.

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FileUp } from 'lucide-react'
import {
  useConfirmVouchers,
  useDiscardVoucherRun,
  useRefreshVoucherRun,
  useStageVouchers,
  useUndoVouchers,
  voucherRun,
  type VoucherRun,
} from '@/api/queries/tallyImport'
import { useInvalidateClient } from '@/api/queries/clients'
import { Checkbox } from '@/components/ui/controls'
import { Confirm } from '@/components/ca/Confirm'
import { PagedList } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { plural } from '@/lib/format'
import { toast } from '@/lib/toast'
import { BankReportStep } from './BankReportStep'
import { ChartStep } from './ChartStep'
import { ImportQueue } from './ImportQueue'
import { SetupStep } from './SetupStep'

const STANDARD_TYPE_CHOICES: [string, string][] = [
  ['sales', 'Sales'],
  ['purchase', 'Purchase'],
  ['credit note', 'Credit note'],
  ['debit note', 'Debit note'],
  ['journal', 'Journal'],
  ['payment', 'Payment'],
  ['receipt', 'Receipt'],
  ['contra', 'Contra'],
]

const messageOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.')

export function TallyImportScreen({ clientId }: { clientId: string }) {
  const stage = useStageVouchers(clientId)
  const confirm = useConfirmVouchers(clientId)
  const undo = useUndoVouchers(clientId)
  const refresh = useRefreshVoucherRun(clientId)
  const discard = useDiscardVoucherRun(clientId)
  const queryClient = useQueryClient()
  const invalidateClient = useInvalidateClient(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [run, setRun] = useState<VoucherRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [undoing, setUndoing] = useState(false)
  const [agree, setAgree] = useState(false)
  // What the person says each of the firm's own voucher types counts as (Tally's name -> standard type).
  const [counts, setCounts] = useState<Record<string, string>>({})

  async function choose(chosen: File | undefined) {
    if (!chosen) return
    setError(null)
    setRun(null)
    setCounts({})
    setAgree(false)
    try {
      setRun(await stage.mutateAsync({ file: chosen }))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  async function open(id: string) {
    setError(null)
    setAgree(false)
    try {
      setRun(await queryClient.fetchQuery({ ...voucherRun(clientId, id), staleTime: 0 }))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  // The stored file is read again: with what the person said their own voucher types count as, or just against today's ledgers.
  async function readAgain(voucherTypes?: Record<string, string>) {
    if (!run) return
    setError(null)
    try {
      setRun(await refresh.mutateAsync({ runId: run.id, voucherTypes }))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  async function removeFromQueue() {
    if (!run) return
    try {
      setRun(await discard.mutateAsync(run.id))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  async function post() {
    if (!run) return
    setError(null)
    try {
      setRun(await confirm.mutateAsync({ runId: run.id, allowOverlap: agree }))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  // Posting is done by a worker, so the screen follows it: the run is read every couple of seconds until it is posted or has stopped.
  const posting = run?.posting ? run.id : null
  useEffect(() => {
    if (!posting) return
    const timer = setInterval(() => {
      void queryClient.fetchQuery({ ...voucherRun(clientId, posting), staleTime: 0 }).then((latest) => {
        setRun(latest)
        if (!latest.posting) {
          void invalidateClient()
          void queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] })
          if (latest.status === 'CONFIRMED') toast.success(`${plural(latest.result?.posted ?? 0, 'voucher')} posted`)
        }
      })
    }, 2000)
    return () => clearInterval(timer)
  }, [posting, clientId, queryClient, invalidateClient])

  async function takeBack() {
    if (!run) return
    const undone = await undo.mutateAsync(run.id)
    setRun(undone)
    toast.success('The import was taken back')
  }

  const skipped = run?.rows.filter((r) => r.action === 'skip') ?? []
  const noted = run?.rows.filter((r) => r.action === 'post' && r.note) ?? []

  return (
    <div className="grid gap-4">
      <SetupStep clientId={clientId} />
      <ChartStep clientId={clientId} />
      <Card className="grid gap-3 p-4">
        <h2 className="font-medium">2. The vouchers</h2>
        <p className="text-sm text-muted-foreground">
          Choose the vouchers exported from Tally, as XML or JSON. Each voucher is posted to the books exactly as Tally had it, and invoices become bills. Import the
          client's ledgers first: a voucher that names a ledger AutoCA does not have is left out, and the preview says which.
        </p>
        <div>
          <input
            ref={input}
            type="file"
            accept=".xml,.json,text/xml,application/json"
            aria-label="Vouchers file"
            className="sr-only"
            onChange={(e) => {
              void choose(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          <Button variant="outline" loading={stage.isPending} onClick={() => input.current?.click()}>
            <FileUp aria-hidden /> Choose the vouchers file
          </Button>
        </div>
      </Card>

      <ImportQueue clientId={clientId} onOpen={(id) => void open(id)} openId={run?.id} />

      <BankReportStep
        clientId={clientId}
        onStaged={(staged) => {
          setError(null)
          setRun(staged)
        }}
        onError={setError}
      />

      {error && (
        <Card tone="danger" role="alert" className="p-3 text-sm">
          {error}
        </Card>
      )}

      {run && run.status === 'PREVIEW' && (
        <Card className="grid gap-3 p-4">
          <h3 className="font-medium">Preview</h3>
          <p className="text-sm" data-testid="counts">
            {plural(run.counts.vouchers, 'voucher')} from {run.counts.date_from} to {run.counts.date_to}: {run.counts.will_post} will be posted
            {run.counts.will_make_bill ? ` (${plural(run.counts.will_make_bill, 'bill')} made)` : ''}
            {run.counts.bank_rows ? `, ${plural(run.counts.bank_rows, 'bank statement row')} written` : ''}
            {run.counts.stock_lines ? `, ${plural(run.counts.stock_lines, 'stock line')} recorded` : ''}, {run.counts.skipped} left out.
          </p>
          {Object.keys(run.counts.unknown_types ?? {}).length > 0 && (
            <div className="grid gap-2 rounded-lg border border-border-strong p-3 text-sm" data-testid="unknown-types">
              <p>
                Some vouchers are of a type this firm made up in Tally. Say what each counts as and they are read like that type; until
                then they are left out.
              </p>
              {Object.entries(run.counts.unknown_types ?? {}).map(([type, n]) => (
                <label key={type} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-40">
                    <strong className="font-semibold">{type}</strong> ({plural(n, 'voucher')}) counts as
                  </span>
                  <Select
                    aria-label={`What ${type} counts as`}
                    value={counts[type] ?? ''}
                    onChange={(e) => setCounts((c) => ({ ...c, [type]: e.target.value }))}
                  >
                    <option value="">Leave these out</option>
                    {STANDARD_TYPE_CHOICES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
              <div>
                <Button
                  variant="outline"
                  loading={refresh.isPending}
                  disabled={!Object.values(counts).some(Boolean)}
                  onClick={() => void readAgain({ ...run.counts.type_map, ...Object.fromEntries(Object.entries(counts).filter(([, v]) => v)) })}
                >
                  Read them like that
                </Button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {Object.entries(run.counts.by_type).map(([type, n]) => (
              <span key={type} className="rounded-full border px-2 py-0.5">
                {type} {n}
              </span>
            ))}
          </div>
          {run.counts.bank_waiting > 0 && (
            <Card tone="attention" className="flex gap-2 p-3 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>
                {plural(run.counts.bank_waiting, 'bank voucher')} {run.counts.bank_waiting === 1 ? 'is' : 'are'} left out (the reason is listed below), so this client's bank ledger will be missing {run.counts.bank_waiting === 1 ? 'that entry' : 'those entries'}.
              </span>
            </Card>
          )}
          {noted.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-muted-foreground">
              {noted.slice(0, 5).map((r) => (
                <li key={r.ordinal}>
                  {r.type} {r.number}: {r.note}
                </li>
              ))}
              {noted.length > 5 && <li>and {noted.length - 5} more.</li>}
            </ul>
          )}
          {skipped.length > 0 && (
            <div className="grid gap-1">
              <h4 className="text-sm font-medium">Left out</h4>
              <PagedList rows={skipped} resetKey={run.id} label="vouchers left out" section="proposals">
                {(items) => (
                  <ul className="grid gap-1 text-sm">
                    {items.map((r) => (
                      <li key={`${r.ordinal}-${r.number}`} className="rounded border p-2">
                        <span className="font-medium">
                          {r.type} {r.number}
                        </span>{' '}
                        <span className="text-muted-foreground">{r.reason}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </PagedList>
            </div>
          )}
          {((run.counts.existing_entries ?? 0) > 0 || (run.counts.existing_statement_rows ?? 0) > 0) && (
            <Card tone="attention" className="grid gap-2 p-3 text-sm" data-testid="overlap">
              <span className="flex gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  This client already has {plural(run.counts.existing_entries ?? 0, 'entry', 'entries')}
                  {(run.counts.existing_statement_rows ?? 0) > 0 ? ` and ${plural(run.counts.existing_statement_rows ?? 0, 'bank statement row')}` : ''} between{' '}
                  {run.counts.date_from} and {run.counts.date_to}. A voucher already imported from Tally is never written twice, but entries made here for the same
                  money would be counted twice.
                </span>
              </span>
              <label className="flex items-center gap-2">
                <Checkbox checked={agree} onChange={(e) => setAgree(e.target.checked)} aria-label="Import anyway" />
                <span>I have looked at them. Import anyway.</span>
              </label>
            </Card>
          )}
          {run.error && (
            <Card tone="danger" role="alert" className="p-3 text-sm">
              The last attempt to post stopped: {run.error}
            </Card>
          )}
          {run.posting ? (
            <div className="grid gap-1" role="status">
              <p className="text-sm font-medium">
                Posting {run.progress?.done ?? 0} of {run.progress?.total ?? run.counts.will_post}…
              </p>
              <div
                role="progressbar"
                aria-label="Posting progress"
                aria-valuemin={0}
                aria-valuemax={run.progress?.total ?? run.counts.will_post}
                aria-valuenow={run.progress?.done ?? 0}
                className="h-2 overflow-hidden rounded bg-muted"
              >
                <div
                  className="h-full bg-primary transition-[width]"
                  style={{ width: `${Math.min(100, Math.round(((run.progress?.done ?? 0) / Math.max(run.progress?.total ?? run.counts.will_post, 1)) * 100))}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">You can leave this page; the vouchers are written in the background.</p>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                loading={confirm.isPending}
                disabled={
                  run.counts.will_post === 0 ||
                  (((run.counts.existing_entries ?? 0) > 0 || (run.counts.existing_statement_rows ?? 0) > 0) && !agree)
                }
                onClick={() => void post()}
              >
                Post {plural(run.counts.will_post, 'voucher')}
              </Button>
              <Button variant="outline" loading={refresh.isPending} onClick={() => void readAgain()}>
                Read it again
              </Button>
              <Button variant="ghost" loading={discard.isPending} onClick={() => void removeFromQueue()}>
                Discard
              </Button>
            </div>
          )}
        </Card>
      )}

      {run && run.status === 'CONFIRMED' && (
        <Card tone="success" className="grid gap-2 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="size-4" aria-hidden /> {plural(run.result?.posted ?? 0, 'voucher')} posted, {plural(run.result?.bills ?? 0, 'bill')} made.
          </div>
          {(run.result?.bank_rows ?? 0) > 0 && <p>{plural(run.result?.bank_rows ?? 0, 'bank statement row')} written, placed as Tally had them.</p>}
          {(run.result?.stock_entries ?? 0) > 0 && <p>{plural(run.result?.stock_entries ?? 0, 'stock movement')} recorded in the stock register.</p>}
          {(run.result?.rules_learned ?? 0) > 0 && <p>{plural(run.result?.rules_learned ?? 0, 'rule')} learned from how it was placed in Tally. They suggest a ledger; nothing posts on its own.</p>}
          {(run.result?.unmatched_bills ?? 0) > 0 && (
            <p>
              {plural(run.result?.unmatched_bills ?? 0, 'bill reference')} on payments could not be applied to a bill here, and {run.result?.unmatched_bills === 1 ? 'is' : 'are'} left on account for you to apply.
            </p>
          )}
          {(run.result?.skipped ?? 0) > 0 && <p>{plural(run.result?.skipped ?? 0, 'voucher')} had been imported before, so were not written again.</p>}
          {(run.result?.failed?.length ?? 0) > 0 && (
            <ul className="list-disc pl-5">
              {run.result?.failed?.map((f) => (
                <li key={f.guid}>{f.reason}</li>
              ))}
            </ul>
          )}
          <div>
            <Button variant="outline" onClick={() => setUndoing(true)}>
              Take this import back
            </Button>
          </div>
        </Card>
      )}

      {run && run.status === 'DISCARDED' && (
        <Card className="p-4 text-sm">
          {(run.result?.undone ?? 0) > 0
            ? `${plural(run.result?.undone ?? 0, 'voucher')} taken back out of the books.`
            : "This import was discarded. The file stays with the client's documents."}
        </Card>
      )}

      <Confirm
        open={undoing}
        onOpenChange={setUndoing}
        title="Take this import back?"
        confirmLabel="Take it back"
        destructive
        onConfirm={async () => {
          try {
            await takeBack()
          } catch (e) {
            setError(messageOf(e))
          }
        }}
      >
        Every entry and bill this import wrote is removed. This is refused once a payment has been applied to one of its bills.
      </Confirm>
    </div>
  )
}
