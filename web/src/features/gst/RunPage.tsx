// One GSTIN's reconciliation for one month: the steps, the figures, and every invoice that needs a
// person. The report is the server's; nothing is recomputed here beyond adding the four tax heads of
// an invoice. A signed-off run is read-only.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft, Check, ChevronDown, ChevronRight, Download, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { errorTitle, isApiError, messageOf } from '@/api/errors'
import { clientDetail } from '@/api/queries/clients'
import { gstExport, gstRun, useGstActions } from '@/api/queries/gst'
import type { GstGroup, GstGstr3bLine, GstReport, GstRow } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/table'
import { saveFile } from '@/platform/download'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { DecisionDialog } from './DecisionDialog'
import {
  currentStep,
  DECISION_BADGE,
  differenceOf,
  differenceWords,
  fileProblem,
  findRow,
  invoiceOf,
  isCreditNote,
  listFormats,
  matched,
  mayFinalise,
  needsDecision,
  periodName,
  PORTAL_FORMATS,
  REGISTER_FORMATS,
  signOffGate,
  startsOpen,
  stepsOf,
  taxOf,
  type StepKey,
} from './logic'

export function RunPage({ clientId, runId }: { clientId: string; runId: string }) {
  const { can, me } = useSession()
  const run = useQuery(gstRun(clientId, runId))
  const client = useQuery(clientDetail(clientId))
  const actions = useGstActions(clientId)
  const report = run.data
  usePageTitle(report ? `GST ${report.registration.gstin}, ${periodName(report.period_start)}` : 'GST reconciliation')

  const [deciding, setDeciding] = useState<string | null>(null)
  const [signing, setSigning] = useState(false)
  // Files uploaded since the last match: the matches on screen do not include them yet.
  const [stale, setStale] = useState(false)

  if (run.error) {
    return (
      <div className="grid gap-4">
        <BackLink clientId={clientId} />
        <ErrorState error={run.error} retry={() => void run.refetch()} />
      </div>
    )
  }
  if (!report) {
    return (
      <div className="grid gap-4">
        <BackLink clientId={clientId} />
        <Spinner label="Opening the reconciliation…" />
      </div>
    )
  }

  const signedOff = report.status === 'signed_off'
  const canPrepare = can('gst.prepare') && !signedOff
  // Until the client has loaded, its lead is unknown, so nobody is offered the sign-off button yet.
  const who = {
    permitted: can('gst.sign_off'),
    role: me?.role,
    membershipId: me?.membership_id,
    leadId: client.data ? (client.data.lead?.id ?? null) : 'unknown',
  }
  const gate = signOffGate(report, who)
  const canFinalise = mayFinalise(who)
  const found = deciding ? findRow(report, deciding) : undefined

  async function exportXlsx() {
    try {
      const { blob, filename } = await gstExport(clientId, runId)
      await saveFile(filename ?? `gst-reconciliation-${report!.period_start.slice(0, 7)}.xlsx`, blob)
    } catch (e) {
      toast.error(`Could not export the working paper. ${messageOf(e)}`)
    }
  }

  return (
    <div className="grid gap-6 [&>*]:min-w-0">
      <div className="grid gap-3">
        <BackLink clientId={clientId} />
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold leading-7 text-heading">
              <span className="num">{report.registration.gstin}</span> <span className="font-normal text-muted-foreground">·</span> {periodName(report.period_start)}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              {signedOff ? (
                <Badge tone="done">Signed off {formatDateTime(report.signed_off_at).slice(0, 10)}</Badge>
              ) : (
                <Badge tone="neutral">Draft</Badge>
              )}
              <span>State code {report.registration.state_code}</span>
            </div>
          </div>
          <Button variant="secondary" onClick={() => void exportXlsx()} disabled={!matched(report)} title={matched(report) ? undefined : 'Run the match first'}>
            <Download /> Export to Excel
          </Button>
        </div>
        {signedOff && <p className="text-sm text-muted-foreground">This run is signed off, so it is read-only. Start a new run for another month.</p>}
      </div>

      <Steps
        report={report}
        canPrepare={canPrepare}
        gate={gate}
        canFinalise={canFinalise}
        stale={stale}
        busy={{ match: actions.match.isPending, upload: actions.upload.isPending || actions.fromBooks.isPending, signOff: actions.signOff.isPending }}
        onFromBooks={async () => {
          const loaded = await actions.fromBooks.mutateAsync(runId)
          setStale(true)
          return loaded
        }}
        onUpload={async (which, file) => {
          await actions.upload.mutateAsync({ runId, which, file })
          setStale(true)
        }}
        onMatch={async () => {
          await actions.match.mutateAsync(runId)
          setStale(false)
        }}
        onSignOff={() => setSigning(true)}
      />

      {matched(report) ? (
        <>
          <Figures report={report} />
          <ActionsForYou report={report} onOpen={setDeciding} />
          <Groups report={report} canPrepare={canPrepare} onOpen={setDeciding} />
          <Gstr3b lines={report.gstr3b} />
        </>
      ) : (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Upload the purchase register and GSTR-2B, then run the match. The figures and the invoices that need a decision appear here.
        </p>
      )}

      {found && (
        <DecisionDialog
          key={found.row.id}
          group={found.group}
          row={found.row}
          canDecide={canPrepare}
          busy={actions.decide.isPending}
          onDecide={(kind, note) => actions.decide.mutateAsync({ runId, match: found.row.id, kind, note })}
          onClose={() => setDeciding(null)}
        />
      )}

      <Confirm
        open={signing}
        onOpenChange={setSigning}
        title={`Sign off ${periodName(report.period_start)} for ${report.registration.gstin}?`}
        confirmLabel="Sign off run"
        onConfirm={async () => {
          await actions.signOff.mutateAsync(runId)
          toast.success('Run signed off')
        }}
        blockedReason={gate.ok ? undefined : gate.reason}
      >
        <p>
          This locks the run. Uploads, the match and decisions cannot be changed afterwards. Eligible credit on this run is <Money paise={report.summary.eligible_paise} />.
        </p>
        <p>The working paper can still be exported.</p>
      </Confirm>
    </div>
  )
}

function BackLink({ clientId }: { clientId: string }) {
  return (
    <Link to={'/clients/$clientId/gst' as never} params={{ clientId } as never} search={{} as never} className="inline-flex w-fit items-center gap-1.5 text-sm text-link hover:underline">
      <ArrowLeft className="size-4" aria-hidden /> All runs for this client
    </Link>
  )
}

// --- steps ------------------------------------------------------------------

function InlineError({ error }: { error: unknown }) {
  const title = isApiError(error) ? errorTitle(error) : undefined
  return (
    <p role="alert" className="text-[13px] text-destructive">
      {title && <strong className="font-semibold">{title}. </strong>}
      {messageOf(error)}
    </p>
  )
}

function Steps({
  report,
  canPrepare,
  gate,
  canFinalise,
  stale,
  busy,
  onUpload,
  onFromBooks,
  onMatch,
  onSignOff,
}: {
  report: GstReport
  canPrepare: boolean
  gate: ReturnType<typeof signOffGate>
  /** The person could sign this run off once the work is done (the button shows, disabled until then). */
  canFinalise: boolean
  stale: boolean
  busy: { match: boolean; upload: boolean; signOff: boolean }
  onUpload: (which: 'register' | 'portal', file: File) => Promise<unknown>
  onFromBooks: () => Promise<{ rows: number; unassigned: number }>
  onMatch: () => Promise<unknown>
  onSignOff: () => void
}) {
  const steps = stepsOf(report)
  const current = currentStep(report)
  const [errors, setErrors] = useState<Partial<Record<StepKey, unknown>>>({})
  const [uploading, setUploading] = useState<'register' | 'portal' | null>(null)
  const registerInput = useRef<HTMLInputElement>(null)
  const portalInput = useRef<HTMLInputElement>(null)

  const fail = (key: StepKey, error: unknown) => setErrors((prev) => ({ ...prev, [key]: error }))
  const clear = (key: StepKey) => setErrors((prev) => ({ ...prev, [key]: undefined }))

  async function picked(which: 'register' | 'portal', files: FileList | null, input: HTMLInputElement | null) {
    const file = files?.[0]
    if (input) input.value = '' // the same file can be chosen again after a fix
    const problem = fileProblem(file, which === 'register' ? REGISTER_FORMATS : PORTAL_FORMATS)
    if (problem) return fail(which, new Error(problem))
    clear(which)
    setUploading(which)
    try {
      await onUpload(which, file!)
      toast.success(which === 'register' ? 'Purchase register uploaded' : 'GSTR-2B uploaded')
    } catch (e) {
      fail(which, e)
    } finally {
      setUploading(null)
    }
  }

  async function fromBooks() {
    clear('register')
    setUploading('register')
    try {
      const loaded = await onFromBooks()
      toast.success(
        loaded.unassigned > 0
          ? `Register taken from the books: ${plural(loaded.rows, 'bill')}. ${plural(loaded.unassigned, 'bill')} with no GSTIN of the client’s were left out.`
          : `Register taken from the books: ${plural(loaded.rows, 'bill')}.`,
      )
    } catch (e) {
      fail('register', e)
    } finally {
      setUploading(null)
    }
  }

  async function match() {
    clear('match')
    try {
      await onMatch()
      toast.success('Matched')
    } catch (e) {
      fail('match', e)
    }
  }

  const ready = report.has_register && report.has_portal
  const unresolved = report.summary.unresolved
  const prim = (key: StepKey) => (current === key ? 'primary' : 'secondary')

  return (
    <section aria-labelledby="gst-steps" className="rounded-lg border bg-card p-5">
      <h3 id="gst-steps" className="text-[15px] font-semibold text-heading">
        Steps
      </h3>
      <ol className="mt-3 grid gap-4">
        {steps.map((step, index) => (
          <li key={step.key} aria-current={current === step.key ? 'step' : undefined} className="grid gap-1.5 sm:grid-cols-[1.75rem_minmax(0,1fr)_auto] sm:items-start sm:gap-x-3">
            <span
              className={cn(
                'grid size-7 place-items-center rounded-full border text-[13px] font-semibold',
                step.done ? 'border-transparent bg-success-bg text-success' : current === step.key ? 'border-primary bg-primary text-primary-foreground' : 'text-muted-foreground',
              )}
              aria-hidden
            >
              {step.done ? <Check className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-heading">
                {step.label}
                <span className="sr-only">{step.done ? ', done' : current === step.key ? ', next' : ', not yet'}</span>
              </div>
              <p className="text-[13px] text-muted-foreground">
                {step.key === 'register' && (report.has_register ? (report.register_from_books ? 'Taken from the books. An uploaded file would replace it.' : 'Uploaded. A new file replaces it.') : `Your purchase register. Accepted: ${listFormats(REGISTER_FORMATS)}.`)}
                {step.key === 'portal' && (report.has_portal ? 'Uploaded. A new file replaces it.' : `The return from the GST portal. Accepted: ${listFormats(PORTAL_FORMATS)}. A JSON file must be this GSTIN’s and this month’s.`)}
                {step.key === 'match' &&
                  (stale
                    ? 'A file was uploaded since the last match. Match again so the figures follow it.'
                    : step.done
                      ? 'Matched. Run it again after replacing a file; your decisions are kept.'
                      : ready
                        ? 'Compare the register with GSTR-2B, invoice by invoice.'
                        : 'Needs both files.')}
                {step.key === 'decide' &&
                  (!matched(report) ? 'Needs the match.' : unresolved > 0 ? `${plural(unresolved, 'difference')} to decide: accept, claim, disallow or decide later.` : 'Every difference has a decision.')}
                {step.key === 'sign_off' && (report.status === 'signed_off' ? 'Signed off.' : gate.ok ? 'Ready. A Senior CA or a firm administrator signs the run off.' : gate.reason)}
              </p>
              {errors[step.key] ? <InlineError error={errors[step.key]} /> : null}
            </div>
            <div className="flex flex-wrap gap-2 sm:justify-end">
              {step.key === 'register' && canPrepare && (
                <>
                  <input ref={registerInput} type="file" className="sr-only" tabIndex={-1} aria-label="Purchase register file" accept={REGISTER_FORMATS.join(',')} onChange={(e) => void picked('register', e.target.files, e.target)} />
                  <Button variant={prim('register')} size="sm" loading={uploading === 'register'} disabled={busy.upload && uploading !== 'register'} onClick={() => registerInput.current?.click()}>
                    <Upload /> {report.has_register ? 'Replace register' : 'Upload register'}
                  </Button>
                  <Button variant="secondary" size="sm" disabled={busy.upload} onClick={() => void fromBooks()}>
                    {report.register_from_books ? 'Reload from the books' : 'Use the books'}
                  </Button>
                </>
              )}
              {step.key === 'portal' && canPrepare && (
                <>
                  <input ref={portalInput} type="file" className="sr-only" tabIndex={-1} aria-label="GSTR-2B file" accept={PORTAL_FORMATS.join(',')} onChange={(e) => void picked('portal', e.target.files, e.target)} />
                  <Button variant={prim('portal')} size="sm" loading={uploading === 'portal'} disabled={busy.upload && uploading !== 'portal'} onClick={() => portalInput.current?.click()}>
                    <Upload /> {report.has_portal ? 'Replace GSTR-2B' : 'Upload GSTR-2B'}
                  </Button>
                </>
              )}
              {step.key === 'match' && canPrepare && (
                <Button variant={stale || current === 'match' ? 'primary' : 'secondary'} size="sm" loading={busy.match} disabled={!ready} onClick={() => void match()}>
                  {step.done ? 'Match again' : 'Match'}
                </Button>
              )}
              {step.key === 'sign_off' && report.status !== 'signed_off' && canFinalise && (
                <Button variant={prim('sign_off')} size="sm" loading={busy.signOff} disabled={!gate.ok} onClick={onSignOff}>
                  Sign off run
                </Button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

// --- figures ----------------------------------------------------------------

function Figures({ report }: { report: GstReport }) {
  const s = report.summary
  return (
    <section aria-label="Credit totals" className="grid gap-2">
      <StatGrid className="lg:grid-cols-3">
        <StatCard label="Eligible ITC" value={<Money paise={s.eligible_paise} />} note="With your decisions applied" />
        <StatCard label="Blocked credit" value={<Money paise={s.blocked_paise} />} note="Section 17(5) categories" />
        <StatCard label="Not claimable" value={<Money paise={s.ineligible_paise} />} note="Not yet, or disallowed" />
        <StatCard label="Reverse-charge tax" value={<Money paise={s.rcm_liability_paise} />} note="Payable, on rows from the books" />
        <StatCard label="In GSTR-2B, not in books" value={<Money paise={s.unclaimed_in_2b_paise} />} note="Tax on invoices not yet booked" tone={s.unclaimed_in_2b_paise ? 'attention' : 'plain'} />
      </StatGrid>
    </section>
  )
}

// --- what to do next --------------------------------------------------------

function ActionsForYou({ report, onOpen }: { report: GstReport; onOpen: (id: string) => void }) {
  const [all, setAll] = useState(false)
  if (report.actions.length === 0) return null
  const shown = all ? report.actions : report.actions.slice(0, 5)
  return (
    <section aria-labelledby="gst-actions" className="rounded-lg border border-accent-edge bg-accent p-4">
      <h3 id="gst-actions" className="text-[15px] font-semibold text-heading">
        Actions for you <span className="num font-normal text-muted-foreground">({report.actions.length})</span>
      </h3>
      <ul className="mt-2 grid gap-1.5 text-sm">
        {shown.map((a) => {
          const row = findRow(report, a.match)?.row
          const inv = row ? invoiceOf(row) : undefined
          return (
            <li key={a.match} className="flex flex-wrap items-baseline gap-x-2">
              <button type="button" className="text-left font-medium text-link underline underline-offset-2" onClick={() => onOpen(a.match)}>
                {inv ? `${inv.supplier_name || 'Unnamed supplier'} · ${inv.invoice_no}` : 'Open the invoice'}
              </button>
              <span className="text-muted-foreground">{a.text}</span>
            </li>
          )
        })}
      </ul>
      {report.actions.length > 5 && (
        <button type="button" className="mt-2 text-[13px] text-link underline underline-offset-2" onClick={() => setAll((v) => !v)}>
          {all ? 'Show fewer' : `Show all ${report.actions.length}`}
        </button>
      )}
    </section>
  )
}

// --- the invoices -----------------------------------------------------------

function Groups({ report, canPrepare, onOpen }: { report: GstReport; canPrepare: boolean; onOpen: (id: string) => void }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(report.groups.filter(startsOpen).map((g) => g.kind)))
  const toggle = (kind: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  return (
    <section aria-labelledby="gst-groups" className="grid gap-3">
      <h3 id="gst-groups" className="text-[15px] font-semibold text-heading">
        Invoices
      </h3>
      <ul className="flex flex-wrap gap-1.5" aria-label="Groups">
        {report.groups.map((g) => (
          <li key={g.kind}>
            <a href={`#gst-${g.kind}`} onClick={() => setOpen((prev) => new Set(prev).add(g.kind))} className="inline-flex h-7 items-center gap-1.5 rounded-md border bg-card px-2.5 text-[13px] hover:bg-hover">
              {g.title} <span className="num font-semibold">{g.count}</span>
            </a>
          </li>
        ))}
      </ul>
      {report.groups.map((g) => (
        <GroupSection key={g.kind} group={g} open={open.has(g.kind)} onToggle={() => toggle(g.kind)} canPrepare={canPrepare} onOpen={onOpen} />
      ))}
    </section>
  )
}

function GroupSection({ group, open, onToggle, canPrepare, onOpen }: { group: GstGroup; open: boolean; onToggle: () => void; canPrepare: boolean; onOpen: (id: string) => void }) {
  const undecided = group.rows.filter((r) => needsDecision(group.kind, r)).length
  const bodyId = `gst-body-${group.kind}`
  const columns: Column<GstRow>[] = [
    {
      key: 'supplier',
      header: 'Supplier',
      sticky: true,
      cell: (r) => {
        const inv = invoiceOf(r)
        return (
          <span className="flex items-center gap-2">
            <span className="block max-w-[22ch] truncate font-medium text-heading" title={`${inv.supplier_name}${inv.gstin ? ` · ${inv.gstin}` : ''}`}>
              {inv.supplier_name || 'Unnamed supplier'}
            </span>
            {isCreditNote(r) && <Badge tone="neutral">Credit note</Badge>}
          </span>
        )
      },
    },
    {
      key: 'invoice',
      header: 'Invoice',
      cell: (r) => {
        const inv = invoiceOf(r)
        return (
          <span>
            {inv.invoice_no} {inv.invoice_date && <span className="text-muted-foreground">· {formatDate(inv.invoice_date)}</span>}
          </span>
        )
      },
    },
    { key: 'bt', header: 'Books taxable ₹', align: 'right', priority: 3, cell: (r) => <Money paise={r.book?.taxable_paise} symbol={false} /> },
    { key: 'bx', header: 'Books tax ₹', align: 'right', priority: 2, cell: (r) => <Money paise={taxOf(r.book)} symbol={false} /> },
    { key: 'pt', header: 'GSTR-2B taxable ₹', align: 'right', priority: 3, cell: (r) => <Money paise={r.portal?.taxable_paise} symbol={false} /> },
    { key: 'px', header: 'GSTR-2B tax ₹', align: 'right', priority: 2, cell: (r) => <Money paise={taxOf(r.portal)} symbol={false} /> },
    {
      key: 'diff',
      header: 'Difference',
      priority: 2,
      cell: (r) => {
        const d = differenceOf(r)
        const words = differenceWords(d.tax) ?? (d.taxable ? `${differenceWords(d.taxable)} (taxable)` : null)
        return words ? <span className="num">{words}</span> : <span className="text-faint">–</span>
      },
    },
    { key: 'eligible', header: 'Eligible ITC ₹', align: 'right', priority: 2, cell: (r) => <Money paise={r.eligible_paise} symbol={false} dash /> },
    {
      key: 'decision',
      header: 'Decision',
      cell: (r) =>
        r.decision ? (
          <Badge tone="done">{DECISION_BADGE[r.decision.kind]}</Badge>
        ) : needsDecision(group.kind, r) ? (
          <Badge tone="attention">Needs a decision</Badge>
        ) : (
          <span className="text-faint">–</span>
        ),
    },
    {
      key: 'open',
      header: <span className="sr-only">Open</span>,
      align: 'right',
      cell: (r) => (
        <Button
          size="sm"
          variant="secondary"
          aria-label={`${canPrepare ? 'Decide on' : 'Open'} ${invoiceOf(r).invoice_no}`}
          onClick={(e) => {
            e.stopPropagation()
            onOpen(r.id)
          }}
        >
          {canPrepare ? 'Decide' : 'Open'}
        </Button>
      ),
    },
  ]

  return (
    <section id={`gst-${group.kind}`} aria-labelledby={`gst-h-${group.kind}`} className="grid scroll-mt-20 gap-2">
      <h4 id={`gst-h-${group.kind}`} className="text-sm">
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className="flex min-h-8 w-full items-center gap-2 rounded-md text-left font-semibold text-heading hover:bg-hover">
          {open ? <ChevronDown className="size-4 shrink-0" aria-hidden /> : <ChevronRight className="size-4 shrink-0" aria-hidden />}
          {group.title}
          <span className="num font-normal text-muted-foreground">{group.count}</span>
          {undecided > 0 && <Badge tone="attention">{undecided} to decide</Badge>}
        </button>
      </h4>
      <div id={bodyId} hidden={!open}>
        {open && <DataTable caption={`${group.title}, ${plural(group.count, 'invoice')}`} columns={columns} rows={group.rows} rowKey={(r) => r.id} onRowClick={(r) => onOpen(r.id)} />}
      </div>
    </section>
  )
}

// --- GSTR-3B ----------------------------------------------------------------

function Gstr3b({ lines }: { lines: GstGstr3bLine[] }) {
  const columns: Column<GstGstr3bLine>[] = [
    { key: 'code', header: 'Table', cell: (l) => <span className="num font-medium">{l.code}</span> },
    { key: 'label', header: 'Description', cell: (l) => <span className="block max-w-[44ch] truncate" title={l.label}>{l.label}</span> },
    { key: 'igst', header: 'IGST ₹', align: 'right', cell: (l) => <Money paise={l.igst_paise} symbol={false} dash /> },
    { key: 'cgst', header: 'CGST ₹', align: 'right', cell: (l) => <Money paise={l.cgst_paise} symbol={false} dash /> },
    { key: 'sgst', header: 'SGST ₹', align: 'right', cell: (l) => <Money paise={l.sgst_paise} symbol={false} dash /> },
    { key: 'cess', header: 'Cess ₹', align: 'right', priority: 2, cell: (l) => <Money paise={l.cess_paise} symbol={false} dash /> },
  ]
  return (
    <section aria-labelledby="gst-3b" className="grid gap-2">
      <div>
        <h3 id="gst-3b" className="text-[15px] font-semibold text-heading">
          GSTR-3B, Table 4
        </h3>
        <p className="text-[13px] text-muted-foreground">Indicative, not the return: what this reconciliation supports. Verify against your ledgers before filing.</p>
      </div>
      <DataTable caption="GSTR-3B Table 4 as supported by this reconciliation, in rupees" columns={columns} rows={lines} rowKey={(l) => l.code} />
    </section>
  )
}
