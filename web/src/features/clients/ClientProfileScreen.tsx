import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { BookOpen, Building2, ChartNoAxesCombined, FileUp, Users } from 'lucide-react'
import { bankAccounts, clientDetail } from '@/api/queries/clients'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'
import { useSession } from '@/session/session'

const SHORTCUTS = [
  {
    to: '/clients/$clientId/bookkeeping',
    title: 'Bookkeeping',
    description: 'Continue this client’s books, review transactions, manage ledgers, and send books for sign-off.',
    action: 'Open bookkeeping',
    icon: BookOpen,
  },
  {
    to: '/clients/$clientId/statements',
    title: 'Bank statements',
    description: 'Upload statements, manage bank accounts, and check statement coverage.',
    action: 'Open statements',
    icon: FileUp,
  },
  {
    to: '/clients/$clientId/reports',
    title: 'Reports',
    description: 'View this client’s trial balance, profit and loss, balance sheet, and bank reconciliation.',
    action: 'Open reports',
    icon: ChartNoAxesCombined,
  },
] as const

export function ClientProfileScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const accounts = useQuery({ ...bankAccounts(clientId), enabled: can('transaction.view') })
  const shortcuts = SHORTCUTS.filter((item) => item.title === 'Bookkeeping'
    ? can('transaction.view') || can('report.view')
    : item.title === 'Bank statements' ? can('transaction.view') : can('report.view'))

  if (client.isPending) return <Spinner label="Loading client details…" />
  if (client.error) return <ErrorState error={client.error} retry={() => void client.refetch()} />

  return (
    <div className="grid max-w-6xl gap-5">
      <section aria-labelledby="profile-title" className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Building2 className="size-4 text-muted-foreground" /><h2 id="profile-title" className="text-[15px] font-semibold text-heading">Client profile</h2></div>
          {(can('team.view') || can('client.update')) && <Button asChild variant="secondary" size="sm"><Link to="/clients/$clientId/team" params={{ clientId }}><Users /> Edit client settings and team</Link></Button>}
        </div>
        <Card className="p-5">
          <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
            <div><dt className="text-xs text-muted-foreground">Senior CA in charge</dt><dd className="mt-1 text-sm font-medium text-heading">{client.data.lead?.name ?? <Badge tone="attention">Not assigned</Badge>}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Financial year starts</dt><dd className="num mt-1 text-sm font-medium text-heading">{formatDate(client.data.fy_start)}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Bank accounts</dt><dd className="num mt-1 text-sm font-medium text-heading">{accounts.data?.count ?? '—'}</dd></div>
            <div><dt className="text-xs text-muted-foreground">Business profile</dt><dd className="mt-1 line-clamp-2 text-sm font-medium text-heading">{client.data.business_profile || 'Not added'}</dd></div>
          </dl>
        </Card>
        {accounts.error && <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />}
      </section>

      <section aria-labelledby="workspaces-title" className="grid gap-3">
        <div><h2 id="workspaces-title" className="text-[15px] font-semibold text-heading">Client workspaces</h2><p className="mt-1 text-sm text-muted-foreground">Choose the area you want to work in. Each opens the client’s own records.</p></div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shortcuts.map(({ to, title, description, action, icon: Icon }) => (
            <Card key={title} className="flex min-h-48 flex-col items-start p-5">
              <span className="grid size-9 place-items-center rounded-lg bg-muted text-primary"><Icon className="size-4" /></span>
              <h3 className="mt-4 text-sm font-semibold text-heading">{title}</h3>
              <p className="mt-1 flex-1 text-[13px] leading-5 text-muted-foreground">{description}</p>
              <Button asChild variant="outline" size="sm" className="mt-4"><Link to={to as never} params={{ clientId } as never}>{action}</Link></Button>
            </Card>
          ))}
        </div>
      </section>
    </div>
  )
}
