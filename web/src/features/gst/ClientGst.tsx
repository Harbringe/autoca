// A client's GST reconciliation: its GSTINs, its runs, and (with ?run=) one run.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { isApiError, messageOf } from '@/api/errors'
import { gstRegistrations, gstRuns, useGstActions } from '@/api/queries/gst'
import type { GstRegistration, GstRun } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { DataTable, type Column } from '@/components/ui/table'
import { maskProblem } from '@/lib/masks'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'
import { defaultPeriod, monthChoices, periodName, periodProblem } from './logic'
import { RunPage } from './RunPage'

const TYPE_LABEL: Record<GstRegistration['registration_type'], string> = {
  regular: 'Regular',
  composition: 'Composition',
  other: 'Other',
}

export function ClientGst({ clientId, runId }: { clientId: string; runId?: string }) {
  usePageTitle('GST reconciliation')
  return runId ? <RunPage clientId={clientId} runId={runId} /> : <RunsAndRegistrations clientId={clientId} />
}

function RunsAndRegistrations({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const navigate = useNavigate()
  const registrations = useQuery(gstRegistrations(clientId))
  const runs = useQuery(gstRuns(clientId))
  const [adding, setAdding] = useState(false)
  const [starting, setStarting] = useState(false)
  const canPrepare = can('gst.prepare')
  const regs = registrations.data ?? []

  const open = (run: GstRun) => void navigate({ to: '/clients/$clientId/gst' as never, params: { clientId } as never, search: { run: run.id } as never })

  const regColumns: Column<GstRegistration>[] = [
    { key: 'gstin', header: 'GSTIN', cell: (r) => <span className="num font-medium text-heading">{r.gstin}</span> },
    { key: 'state', header: 'State code', priority: 2, cell: (r) => <span className="num">{r.state_code}</span> },
    { key: 'type', header: 'Type', cell: (r) => TYPE_LABEL[r.registration_type] },
  ]
  const runColumns: Column<GstRun>[] = [
    { key: 'period', header: 'Return month', sortValue: (r) => r.period_start, cell: (r) => <span className="font-medium text-heading">{periodName(r.period_start)}</span> },
    { key: 'gstin', header: 'GSTIN', sortValue: (r) => r.gstin, cell: (r) => <span className="num">{r.gstin}</span> },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => (r.status === 'signed_off' ? <Badge tone="done">Signed off</Badge> : <Badge tone="neutral">Draft</Badge>),
    },
    {
      key: 'open',
      header: <span className="sr-only">Open</span>,
      align: 'right',
      cell: (r) => (
        <Button
          size="sm"
          variant="secondary"
          aria-label={`Open ${periodName(r.period_start)} for ${r.gstin}`}
          onClick={(e) => {
            e.stopPropagation()
            open(r)
          }}
        >
          Open
        </Button>
      ),
    },
  ]

  return (
    <div className="grid gap-8 [&>*]:min-w-0">
      <section aria-labelledby="gst-regs" className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="gst-regs" className="text-[15px] font-semibold text-heading">
            GSTINs
          </h2>
          {canPrepare && regs.length > 0 && (
            <Button variant="secondary" size="sm" onClick={() => setAdding(true)}>
              <Plus /> Add a GSTIN
            </Button>
          )}
        </div>
        {registrations.error ? (
          <ErrorState error={registrations.error} retry={() => void registrations.refetch()} />
        ) : (
          <DataTable
            caption="This client’s GSTINs"
            columns={regColumns}
            rows={registrations.data}
            loading={registrations.isLoading}
            rowKey={(r) => r.id}
            empty={
              <EmptyState
                title="No GSTIN yet"
                action={
                  canPrepare && (
                    <Button onClick={() => setAdding(true)}>
                      <Plus /> Add a GSTIN
                    </Button>
                  )
                }
              >
                Add the client’s GSTIN to start a reconciliation.{canPrepare ? '' : ' Your role can read this but not add one.'}
              </EmptyState>
            }
          />
        )}
      </section>

      {regs.length > 0 && (
        <section aria-labelledby="gst-runs" className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="gst-runs" className="text-[15px] font-semibold text-heading">
              Reconciliations
            </h2>
            {canPrepare && (
              <Button onClick={() => setStarting(true)}>
                <Plus /> New run
              </Button>
            )}
          </div>
          {runs.error ? (
            <ErrorState error={runs.error} retry={() => void runs.refetch()} />
          ) : (
            <DataTable
              caption="GST reconciliation runs"
              columns={runColumns}
              rows={runs.data}
              loading={runs.isLoading}
              rowKey={(r) => r.id}
              onRowClick={open}
              defaultSort={{ key: 'period', dir: 'desc' }}
              empty={
                <EmptyState
                  title="No reconciliation yet"
                  action={
                    canPrepare && (
                      <Button onClick={() => setStarting(true)}>
                        <Plus /> New run
                      </Button>
                    )
                  }
                >
                  A run compares one month’s purchase register with that month’s GSTR-2B.
                </EmptyState>
              }
            />
          )}
        </section>
      )}

      {adding && <AddGstinDialog clientId={clientId} onClose={() => setAdding(false)} />}
      {starting && <NewRunDialog clientId={clientId} registrations={regs} onClose={() => setStarting(false)} />}
    </div>
  )
}

// --- add a GSTIN ------------------------------------------------------------

export function AddGstinDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const { addRegistration } = useGstActions(clientId)
  const [gstin, setGstin] = useState('')
  const [type, setType] = useState<GstRegistration['registration_type']>('regular')
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    const local = !gstin ? 'Enter the 15-character GSTIN.' : maskProblem('gstin', gstin)
    if (local) return setError(local)
    setError(null)
    try {
      await addRegistration.mutateAsync({ gstin, registration_type: type })
      toast.success(`GSTIN ${gstin} added`)
      onClose()
    } catch (err) {
      // A bad checksum is a 400 naming the field; "already registered" is a 409 with only a sentence.
      setError(isApiError(err) ? (err.field('gstin') ?? err.message) : messageOf(err))
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !next && !addRegistration.isPending && onClose()}>
      <DialogContent aria-describedby="add-gstin-hint">
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Add a GSTIN</DialogTitle>
            <DialogDescription id="add-gstin-hint">The state is read from the first two digits. The server checks the GSTIN’s check character.</DialogDescription>
          </DialogHeader>
          <Field label="GSTIN" mask="gstin" error={error ?? undefined} hint="15 characters, for example 27AABCA1234F1Z5.">
            {(props, mask) => (
              <Input {...props} {...mask} autoFocus value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} autoComplete="off" spellCheck={false} className="num" />
            )}
          </Field>
          <Field label="Registration type">
            {(props) => (
              <Select {...props} value={type} onChange={(e) => setType(e.target.value as typeof type)}>
                <option value="regular">Regular</option>
                <option value="composition">Composition</option>
                <option value="other">Other</option>
              </Select>
            )}
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose} disabled={addRegistration.isPending}>
              Cancel
            </Button>
            <Button type="submit" loading={addRegistration.isPending}>
              Add GSTIN
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// --- new run ----------------------------------------------------------------

function NewRunDialog({ clientId, registrations, onClose }: { clientId: string; registrations: GstRegistration[]; onClose: () => void }) {
  const { newRun } = useGstActions(clientId)
  const navigate = useNavigate()
  const [registration, setRegistration] = useState(registrations[0]?.id ?? '')
  const [period, setPeriod] = useState(() => defaultPeriod(new Date()))
  const [error, setError] = useState<string | null>(null)
  const months = monthChoices(new Date())

  async function submit(e: FormEvent) {
    e.preventDefault()
    const problem = !registration ? 'Choose the GSTIN.' : periodProblem(period, new Date())
    if (problem) return setError(problem)
    setError(null)
    try {
      const report = await newRun.mutateAsync({ registration, period })
      onClose()
      await navigate({ to: '/clients/$clientId/gst' as never, params: { clientId } as never, search: { run: report.id } as never })
    } catch (err) {
      setError(messageOf(err))
    }
  }

  return (
    <Dialog open onOpenChange={(next) => !next && !newRun.isPending && onClose()}>
      <DialogContent aria-describedby="new-run-hint">
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New run</DialogTitle>
            <DialogDescription id="new-run-hint">One GSTIN and one return month. If it already exists you are taken to it.</DialogDescription>
          </DialogHeader>
          <Field label="GSTIN">
            {(props) => (
              <Select {...props} value={registration} onChange={(e) => setRegistration(e.target.value)} autoFocus>
                {registrations.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.gstin}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Return month" error={error ?? undefined}>
            {(props) => (
              <Select {...props} value={period} onChange={(e) => setPeriod(e.target.value)}>
                {months.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose} disabled={newRun.isPending}>
              Cancel
            </Button>
            <Button type="submit" loading={newRun.isPending}>
              Start run
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
