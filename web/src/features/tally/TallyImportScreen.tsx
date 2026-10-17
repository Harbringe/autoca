// Import a client's history from Tally: choose the vouchers export, read the preview, post it, or take a posted import back.
//
// Nothing is posted by choosing the file. The preview says what would be written and, for each voucher it would not write, why.
// The client's ledgers must be in AutoCA first (a voucher naming a ledger that is not there is skipped and says so), and bank vouchers
// are not imported yet, so a run is partial books until they are; the notice says so in plain words.

import { useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, FileUp } from 'lucide-react'
import { useConfirmVouchers, useStageVouchers, useUndoVouchers, type VoucherRun } from '@/api/queries/tallyImport'
import { Confirm } from '@/components/ca/Confirm'
import { PagedList } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { plural } from '@/lib/format'
import { toast } from '@/lib/toast'
import { ChartStep } from './ChartStep'

const messageOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.')

export function TallyImportScreen({ clientId }: { clientId: string }) {
  const stage = useStageVouchers(clientId)
  const confirm = useConfirmVouchers(clientId)
  const undo = useUndoVouchers(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [run, setRun] = useState<VoucherRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [undoing, setUndoing] = useState(false)

  async function choose(file: File | undefined) {
    if (!file) return
    setError(null)
    setRun(null)
    try {
      setRun(await stage.mutateAsync({ file }))
    } catch (e) {
      setError(messageOf(e))
    }
  }

  async function post() {
    if (!run) return
    setError(null)
    try {
      const done = await confirm.mutateAsync(run.id)
      setRun(done)
      toast.success(`${plural(done.result?.posted ?? 0, 'voucher')} posted`)
    } catch (e) {
      setError(messageOf(e))
    }
  }

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
      <ChartStep clientId={clientId} />
      <Card className="grid gap-3 p-4">
        <h2 className="font-medium">2. The vouchers</h2>
        <p className="text-sm text-muted-foreground">
          Choose the vouchers exported from Tally in XML. Each voucher is posted to the books exactly as Tally had it, and invoices become bills. Import the
          client's ledgers first: a voucher that names a ledger AutoCA does not have is left out, and the preview says which.
        </p>
        <div>
          <input
            ref={input}
            type="file"
            accept=".xml,text/xml"
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
            {run.counts.bank_rows ? `, ${plural(run.counts.bank_rows, 'bank statement row')} written` : ''}, {run.counts.skipped} left out.
          </p>
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
          <div>
            <Button loading={confirm.isPending} disabled={run.counts.will_post === 0} onClick={() => void post()}>
              Post {plural(run.counts.will_post, 'voucher')}
            </Button>
          </div>
        </Card>
      )}

      {run && run.status === 'CONFIRMED' && (
        <Card tone="success" className="grid gap-2 p-4 text-sm">
          <div className="flex items-center gap-2 font-medium">
            <CheckCircle2 className="size-4" aria-hidden /> {plural(run.result?.posted ?? 0, 'voucher')} posted, {plural(run.result?.bills ?? 0, 'bill')} made.
          </div>
          {(run.result?.bank_rows ?? 0) > 0 && <p>{plural(run.result?.bank_rows ?? 0, 'bank statement row')} written, placed as Tally had them.</p>}
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
        <Card className="p-4 text-sm">{plural(run.result?.undone ?? 0, 'voucher')} taken back out of the books.</Card>
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
