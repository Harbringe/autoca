// The heading every printed report carries, and the warning when its figures are not final: rows still waiting to be
// posted, or a bank account whose opening balance has not been confirmed. Shared by every report on the Reports tab.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'
import { bankAccounts } from '@/api/queries/clients'
import type { BankAccount, ReportFooter } from '@/api/types'
import { Card } from '@/components/ui/card'
import { formatDate, formatDateTime, plural } from '@/lib/format'

/** Bank accounts whose opening balance nobody has confirmed: the books start short by that amount. */
export function useUnconfirmedOpenings(clientId: string): BankAccount[] {
  const accounts = useQuery(bankAccounts(clientId))
  return (accounts.data?.results ?? []).filter((a) => a.is_active && !a.has_opening_balance)
}

export function OpeningLink({ clientId }: { clientId: string }) {
  return (
    <Link to="/clients/$clientId/statements" params={{ clientId }} className="font-medium underline underline-offset-2">
      Confirm the opening balance
    </Link>
  )
}

/**
 * The heading every printed report carries, and the warning when the figures are not final: rows
 * still waiting, or a bank account whose opening balance has not been confirmed.
 */
export function ReportFrame({
  clientId,
  title,
  footer,
  children,
  period,
}: {
  clientId: string
  title: string
  footer: ReportFooter
  children: ReactNode
  period?: string
}) {
  const unconfirmed = useUnconfirmedOpenings(clientId)
  const provisional = isProvisional(footer, unconfirmed)
  return (
    <Card className="p-5 print:border-0 print:p-0 print:shadow-none">
      <div className="mb-4 text-center">
        <h2 className="text-lg font-semibold text-heading">{footer.client_name}</h2>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">
          {period ?? `for the year ${formatDate(footer.period_start)} to ${formatDate(footer.period_end)} (FY ${footer.fy_label})`}
        </div>
      </div>
      {provisional && (
        <div className="mb-4 flex gap-2 rounded-md border border-accent-edge bg-accent p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-accent-foreground" aria-hidden />
          <div className="grid gap-1">
            <span>
              <strong>Provisional.</strong>
              {!footer.is_complete && (
                <>
                  {' '}
                  <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'pending_approval' }} className="underline underline-offset-2">
                    {plural(footer.pending_review, 'transaction')}
                  </Link>{' '}
                  in this period {footer.pending_review === 1 ? 'is' : 'are'} classified but not
                  yet posted, so {footer.pending_review === 1 ? 'it is' : 'they are'} not in these figures.
                </>
              )}
            </span>
            {unconfirmed.length > 0 && (
              <span>
                Opening balance not confirmed for {unconfirmed.map((a) => a.label).join(', ')}: the bank ledger starts without it and shows
                short. <OpeningLink clientId={clientId} />.
              </span>
            )}
          </div>
        </div>
      )}
      {children}
      <div className="mt-4 border-t pt-2 text-xs text-muted-foreground">
        {footer.client_name} · FY {footer.fy_label} · {plural(footer.entry_count, 'entry', 'entries')} · generated{' '}
        {formatDateTime(footer.generated_at).replace(', ', ' ')}
      </div>
    </Card>
  )
}

export const isProvisional = (footer: ReportFooter, unconfirmed: BankAccount[]) => !footer.is_complete || unconfirmed.length > 0
