// The three dashboards. One page grid of twelve columns, so on a phone the order of the cards can be
// changed (the list of things to do comes before the numbers for a Senior CA and for Staff) without
// repeating any markup. Row 1 is four figures, then the main card, then question-titled cards.
//
// The weekly flow (A5/B6), the people table (A7/B9) and a person's own work (C1-C8) read their own endpoints,
// so each card loads, fails and retries on its own and one slow answer never blanks the page. The people table
// is asked for only by people who may see a team: the server refuses everyone else.

import type { ReactNode } from 'react'
import type { Portfolio } from '@/api/types'
import type { CardState } from '@/components/ca/DashCard'
import { KpiCard } from '@/components/ca/KpiCard'
import { clientHealth, healthCounts, sealingFigures, type HealthCounts } from '@/lib/dashboard'
import { useSession } from '@/session/session'
import { plural } from '@/lib/format'
import { ActionCard, AtRiskCard, BooksDonutCard, DueSoonCard, NeedMeFirstCard, OwedCard, type CardProps } from './cards'
import { ClientHealthTable } from './PortfolioView'
import { DailyFinishedCard, MyKpis, MyProgressCard, MyWorkClientsCard, NextTasksCard, PeopleCard, useMyWork, WorkFlowCard } from './workCards'

export interface LayoutProps {
  data: Portfolio | undefined
  state: CardState
  today: Date
}

const ZEROS: HealthCounts = { total: 0, onTrack: 0, atRisk: 0, overdue: 0, sealLate: 0, tdsLate: 0, monthsLate: 0 }

function Kpis({ children }: { children: ReactNode }) {
  return <div className="col-span-12 grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
}

const span = {
  full: 'col-span-12',
  a: 'col-span-12 lg:col-span-5',
  b: 'col-span-12 lg:col-span-7',
  half: 'col-span-12 xl:col-span-6',
} as const

function lateNote(h: HealthCounts): string {
  const parts = [h.sealLate && `${h.sealLate} past a seal date`, h.tdsLate && `${h.tdsLate} with TDS overdue`, h.monthsLate && `${h.monthsLate} with a month missing`].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'Nothing is late.'
}

/** The four figures that split every client into one place: on track, at risk, late, and how much work waits. */
function HealthKpis({ data, state }: Pick<LayoutProps, 'data' | 'state'>) {
  const loading = state === 'loading'
  const h = data ? healthCounts(data.clients) : ZEROS
  const waiting = data ? data.totals.unresolved + data.totals.pending_approval + data.totals.review_pending + data.totals.ai_unchecked : 0
  return (
    <Kpis>
      <KpiCard
        loading={loading}
        label="Clients on track"
        value={`${h.onTrack} of ${h.total}`}
        note="Nothing late, nothing failing"
        progress={{ value: h.onTrack, max: h.total, label: `${h.onTrack} of ${plural(h.total, 'client')} on track` }}
        to="/clients"
      />
      <KpiCard loading={loading} label="Clients at risk" value={h.atRisk} note="A check is failing or items block sealing" tone={h.atRisk ? 'attention' : 'plain'} to="/alerts" />
      <KpiCard loading={loading} label="Late right now" value={h.overdue} note={lateNote(h)} tone={h.overdue ? 'attention' : 'plain'} to="/alerts" />
      <KpiCard
        loading={loading}
        label="Work waiting"
        value={waiting}
        note="Entries to sort or record, and books to review"
        to="/pipeline"
      />
    </Kpis>
  )
}

export function OwnerDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const { can } = useSession()
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <HealthKpis data={data} state={state} />
      <div className={span.b}>
        <WorkFlowCard title="Is work getting done as fast as it arrives?" />
      </div>
      <div className={span.a}>
        <BooksDonutCard {...props} title="Where are my clients' books today?" empty="No clients yet. Add a client and upload its bank statement." />
      </div>
      <div className={span.full}>
        <NeedMeFirstCard {...props} />
      </div>
      {can('team.view') && (
        <div className={span.full}>
          <PeopleCard />
        </div>
      )}
      <div className={span.half}>
        <DueSoonCard {...props} today={today} />
      </div>
      <div className={span.half}>
        <OwedCard {...props} />
      </div>
      <div className={span.full}>
        <ClientHealthTable data={data} state={state} />
      </div>
    </div>
  )
}

export function SeniorDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const loading = state === 'loading'
  const clients = data?.clients ?? []
  const health = clients.map(clientHealth)
  const { can } = useSession()
  const seal = sealingFigures(clients)
  const waitingOnMe = seal.waitingForApproval || clients.filter((c) => c.review_pending).length
  const sealLate = clients.filter((c) => c.seal_due).length
  const risk = health.filter((h) => h.health !== 'on_track').length
  const work = data ? data.totals.unresolved + data.totals.pending_approval : 0
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <Kpis>
        <KpiCard loading={loading} label="Books waiting for my approval" value={waitingOnMe} note={waitingOnMe ? (seal.oldestDays ? `The oldest has waited ${plural(seal.oldestDays, 'day')}` : 'Sent to you for review') : 'Nothing sent to you'} tone={waitingOnMe ? 'attention' : 'plain'} to="/pipeline" />
        <KpiCard loading={loading} label="Books ready to seal" value={seal.readyToSeal} note={seal.readyToSeal ? 'Approved, nothing changed since' : sealLate ? `${sealLate} past their seal date, not ready` : 'None ready yet'} tone={sealLate ? 'attention' : 'plain'} to="/alerts" />
        <KpiCard loading={loading} label="At risk or late" value={`${risk} of ${clients.length}`} note="Clients with something late or failing" tone={risk ? 'attention' : 'plain'} to="/alerts" />
        <KpiCard loading={loading} label="Entries still to do" value={work} note="To sort into accounts or to record" to="/pipeline" />
      </Kpis>
      <div className={`${span.b} max-lg:order-first`}>
        <ActionCard
          {...props}
          title="What is waiting on me?"
          hint="Late things first, then books to sign off, then the rest. Each button opens the exact screen."
          empty="Nothing is waiting on you."
        />
      </div>
      <div className={span.a}>
        <BooksDonutCard {...props} title="Where are my clients' books?" empty="No clients are assigned to you or your team." />
      </div>
      <div className={span.b}>
        <WorkFlowCard title="Is my team keeping up?" />
      </div>
      <div className={span.a}>
        <DueSoonCard {...props} today={today} />
      </div>
      <div className={span.full}>
        <AtRiskCard {...props} />
      </div>
      {can('team.view') && (
        <div className={span.full}>
          <PeopleCard title="What is each person on my team doing?" />
        </div>
      )}
    </div>
  )
}

export function StaffDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const mine = useMyWork()
  const loading = mine.isLoading
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <MyKpis data={mine.data} loading={loading} />
      <div className={`${span.b} max-lg:order-first`}>
        <NextTasksCard data={mine.data} loading={loading} error={mine.error} />
      </div>
      <div className={span.a}>
        <MyProgressCard data={mine.data} loading={loading} />
      </div>
      <div className={span.b}>
        <DailyFinishedCard data={mine.data} loading={loading} />
      </div>
      <div className={span.a}>
        <MyWorkClientsCard data={mine.data} loading={loading} />
      </div>
      <div className={span.full}>
        <DueSoonCard {...props} today={today} />
      </div>
    </div>
  )
}
