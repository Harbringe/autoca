// The three dashboards. One page grid of twelve columns, so on a phone the order of the cards can be
// changed (the list of things to do comes before the numbers for a Senior CA and for Staff) without
// repeating any markup. Row 1 is a strip of headline tiles, then the pipeline and client health, then the work.
//
// The weekly flow (A5/B6), the people table (A7/B9) and a person's own work (C1-C8) read their own endpoints,
// so each card loads, fails and retries on its own and one slow answer never blanks the page. The people table
// is asked for only by people who may see a team: the server refuses everyone else.

import type { ReactNode } from 'react'
import type { Portfolio } from '@/api/types'
import type { CardState } from '@/components/ca/DashCard'
import { healthCounts, standingContext } from '@/lib/dashboard'
import { useSession } from '@/session/session'
import { ActionCard, AtRiskCard, DueSoonCard, OwedCard, type CardProps } from './cards'
import { ClientHealthTable } from './PortfolioView'
import { ActivityCard, HealthCard, OwnerStrip, PipelineCard, PriorityCard, SeniorStrip, StaffListCard, WorkColumnsCard } from './commandCards'
import { DailyFinishedCard, MyKpis, MyProgressCard, MyWorkClientsCard, NextTasksCard, useMyWork, WorkFlowCard } from './workCards'

export interface LayoutProps {
  data: Portfolio | undefined
  state: CardState
  today: Date
}

/** The table behind the pictures: still there for anyone who wants the rows, one click away. */
function Behind({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="group rounded-lg border bg-card">
      <summary className="flex min-h-11 cursor-pointer items-center px-5 text-[15px] font-semibold text-heading">{label}</summary>
      <div className="px-1 pb-1">{children}</div>
    </details>
  )
}

const span = {
  full: 'col-span-12',
  a: 'col-span-12 lg:col-span-5',
  b: 'col-span-12 lg:col-span-7',
  half: 'col-span-12 xl:col-span-6',
} as const

export function OwnerDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const { can } = useSession()
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <div className={span.full}>
        <OwnerStrip {...props} today={today} />
      </div>
      <div className={span.b}>
        <PipelineCard {...props} />
      </div>
      <div className={span.a}>
        <HealthCard {...props} today={today} />
      </div>
      <div className={span.b}>
        <WorkColumnsCard {...props} />
      </div>
      <div className={span.a}>
        <DueSoonCard {...props} today={today} />
      </div>
      {can('team.view') && (
        <div className={span.half}>
          <StaffListCard />
        </div>
      )}
      <div className={can('team.view') ? span.half : span.full}>
        <PriorityCard {...props} today={today} />
      </div>
      <div className={span.half}>
        <WorkFlowCard title="Is work getting done as fast as it arrives?" />
      </div>
      {can('audit.view') ? (
        <div className={span.half}>
          <ActivityCard />
        </div>
      ) : (
        <div className={span.half}>
          <OwedCard {...props} />
        </div>
      )}
      {can('audit.view') && (
        <div className={span.full}>
          <OwedCard {...props} />
        </div>
      )}
      <div className={span.full}>
        <Behind label="Show the table of every client">
          <ClientHealthTable data={data} state={state} />
        </Behind>
      </div>
    </div>
  )
}

export function SeniorDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const { can } = useSession()
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <div className={span.full}>
        <SeniorStrip {...props} today={today} />
      </div>
      <div className={span.b}>
        <PipelineCard {...props} title="Where are my clients' books?" />
      </div>
      <div className={span.a}>
        <HealthCard {...props} today={today} />
      </div>
      <div className={`${span.b} max-lg:order-first`}>
        <ActionCard
          {...props}
          today={today}
          title="What is waiting on me?"
          hint="Late first, then books to sign off, then the rest."
          empty="Nothing is waiting on you."
        />
      </div>
      <div className={span.a}>
        <DueSoonCard {...props} today={today} />
      </div>
      <div className={span.b}>
        <WorkColumnsCard {...props} />
      </div>
      <div className={span.a}>
        <PriorityCard {...props} today={today} />
      </div>
      {can('team.view') && (
        <div className={span.half}>
          <StaffListCard title="What is each person on my team doing?" />
        </div>
      )}
      <div className={can('team.view') ? span.half : span.full}>
        <WorkFlowCard title="Is my team keeping up?" />
      </div>
      <div className={span.full}>
        <AtRiskCard {...props} today={today} />
      </div>
    </div>
  )
}

export function StaffDashboard({ data, state, today }: LayoutProps) {
  const props: CardProps = { data, state }
  const mine = useMyWork()
  const loading = mine.isLoading
  const late = data ? healthCounts(data.clients, standingContext(data, today)).overdue : 0
  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <MyKpis data={mine.data} loading={loading} late={late} lateLoading={state === 'loading'} />
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
