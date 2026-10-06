// A module the product has planned but not built. It is a real page, reachable from the sidebar,
// that says what the module will do and what to use meanwhile. Nothing else: no mock screenshots,
// no sign-up, no progress bar.

import { Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/ca/Page'
import { ComingSoon } from '@/components/ui/coming-soon'
import { SOON_MODULES, type SoonModule } from '@/lib/modules'
import { usePageTitle } from '@/lib/title'

interface Copy {
  name: string
  sentence: string
  until: { text: string; to: string; label: string }
}

const COPY: Record<SoonModule, Copy> = {
  taxation: {
    name: 'Taxation / ITR',
    sentence: 'Income-tax and advance-tax workings from the closed books.',
    until: { text: 'Export the books to Tally from', to: '/bookkeeping', label: 'Books & sign-off' },
  },
  audit: {
    name: 'Audit',
    sentence: 'Audit programmes and working papers per client.',
    until: { text: 'Sign-offs and corrections are kept in the history under', to: '/bookkeeping', label: 'Books & sign-off' },
  },
  compliance: {
    name: 'Compliance',
    sentence: 'A calendar of due dates per client, with reminders.',
    until: { text: 'The month’s GST reconciliation is under', to: '/gst', label: 'GST reconciliation' },
  },
  ai: {
    name: 'AI assistant',
    sentence: 'Ask questions across a client’s books in plain language.',
    until: { text: 'The assistant already reads bank rows: see', to: '/bank', label: 'Bank statements' },
  },
  analytics: {
    name: 'Firm analytics',
    sentence: 'Turnover, realisation and load across the firm.',
    until: { text: 'What each person did is counted under', to: '/staff', label: 'Staff performance' },
  },
}

export function isSoonModule(value: string): value is SoonModule {
  return (SOON_MODULES as readonly string[]).includes(value)
}

export function SoonScreen({ module }: { module: string }) {
  const copy = isSoonModule(module) ? COPY[module] : undefined
  usePageTitle(copy ? `${copy.name} (coming soon)` : 'Not found')
  if (!copy) {
    return (
      <div className="grid gap-4">
        <PageHeader title="Page not found" description="There is no module with that name." />
        <Link to="/clients" className="text-link underline">
          Go to Clients
        </Link>
      </div>
    )
  }
  return (
    <ComingSoon name={copy.name} sentence={copy.sentence}>
      {copy.until.text}{' '}
      <Link to={copy.until.to as never} className="font-medium text-link underline">
        {copy.until.label}
      </Link>
      .
    </ComingSoon>
  )
}
