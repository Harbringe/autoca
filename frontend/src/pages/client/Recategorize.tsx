import { useState } from 'react'
import { api, V1, waitForJob } from '../../api/client'
import type { Client, Job } from '../../api/types'
import { Button } from '../../components/ui'

export type Flash = { tone: 'good' | 'warn' | 'bad' | 'info'; text: string }

export function RecategorizeButton({
  client,
  statementId,
  label = 'Re-categorize with AI',
  disabled,
  onBusy,
  onResult,
}: {
  client: Client
  statementId?: string
  label?: string
  disabled?: boolean
  onBusy?: (busy: boolean) => void
  onResult: (flash: Flash) => void
}) {
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    onBusy?.(true)
    try {
      const started = await api.post<Job>(`${V1}/clients/${client.id}/review-queue/recategorize/`, statementId ? { statement: statementId } : {})
      const job = await waitForJob(started)
      if (job.status === 'FAILED') throw new Error(job.error || 'Re-categorizing failed.')
      const r = job.result as Record<string, number | string>
      if (r.error) {
        onResult({ tone: 'warn', text: `The model could not be reached: ${String(r.error)}. Nothing was changed after that point.` })
      } else if (Number(r.considered) === 0) {
        onResult({ tone: 'info', text: 'Nothing to re-categorize: every row is either posted, placed by a person, or no model is configured.' })
      } else {
        onResult({
          tone: 'good',
          text: `AI looked at ${String(r.considered)} rows: changed ${String(r.suggested)}, agreed with the existing rule on ${String(r.confirmed)}, left ${String(r.declined)} as they were.${Number(r.proposed) > 0 ? ` Proposed ${String(r.proposed)} new ledger${Number(r.proposed) === 1 ? '' : 's'}, waiting for a CA under Chart of accounts.` : ''} Changed rows are in the review queue and still need a person.`,
        })
      }
    } catch (err) {
      onResult({ tone: 'bad', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
      onBusy?.(false)
    }
  }

  return (
    <Button className="btn-sm" onClick={() => void run()} busy={busy} disabled={disabled || busy}>
      {label}
    </Button>
  )
}
