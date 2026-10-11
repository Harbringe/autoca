import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FigureTile } from '@/components/ca/FigureTile'
import { Users } from 'lucide-react'
import { CountColumns } from './CountColumns'
import { HealthDonut } from './HealthDonut'
import { PipelineBar } from './PipelineBar'

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

describe('FigureTile', () => {
  it('shows one big number, its caption and a change in words', () => {
    render(<FigureTile icon={Users} label="Clients" value={12} caption="Fully signed off" delta={{ direction: 'up', text: '3 more', good: true }} />)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('Fully signed off')).toBeInTheDocument()
    expect(screen.getByText('3 more')).toBeInTheDocument()
  })
  it('is a link when it counts something with its own screen', () => {
    render(<FigureTile icon={Users} label="Late" value={2} to="/alerts" />)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/alerts')
  })
  it('draws a skeleton, named for a screen reader, while loading', () => {
    render(<FigureTile icon={Users} label="Clients" value={1} loading />)
    expect(screen.getByText('Loading: Clients')).toBeInTheDocument()
  })
  it('draws a sparkline only from a real series of two points or more', () => {
    const { rerender } = render(<FigureTile icon={Users} label="Done" value={5} spark={{ values: [1], label: 'one point' }} />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    rerender(<FigureTile icon={Users} label="Done" value={5} spark={{ values: [1, 3, 2], label: 'three weeks' }} />)
    expect(screen.getByRole('img', { name: 'three weeks' })).toBeInTheDocument()
  })
})

const stages = [
  { key: 'a', label: 'No statements', count: 0, tone: 'context' as const },
  { key: 'b', label: 'Needs a ledger', count: 3, tone: 'watch' as const, to: '/clients' },
  { key: 'c', label: 'Signed off', count: 9, tone: 'good' as const, to: '/clients' },
]

describe('PipelineBar', () => {
  it('writes the count on every stage, including an empty one, and has the same data in a hidden table', () => {
    render(<PipelineBar stages={stages} unit="clients" ariaLabel="12 clients by stage" caption="Clients by stage" />)
    expect(screen.getByRole('img', { name: '12 clients by stage' })).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Clients by stage' })
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
  })
  it('draws an empty bar when there is nothing, and one stage fills it', () => {
    const { rerender } = render(<PipelineBar stages={stages.map((s) => ({ ...s, count: 0 }))} unit="clients" ariaLabel="0 clients" caption="c" />)
    expect(screen.getByRole('img', { name: '0 clients' }).children).toHaveLength(0)
    rerender(<PipelineBar stages={[{ ...stages[2]!, count: 4 }]} unit="clients" ariaLabel="4 clients" caption="c" />)
    expect(screen.getByRole('img', { name: '4 clients' }).children).toHaveLength(1)
  })
})

describe('HealthDonut', () => {
  const parts = (g: number, w: number, b: number) => [
    { key: 'good' as const, label: 'On track', count: g, to: '/clients' },
    { key: 'watch' as const, label: 'At risk', count: w, to: '/alerts' },
    { key: 'bad' as const, label: 'Late', count: b, to: '/alerts' },
  ]
  it('shows the total in the middle and a labelled row with a share for each part', () => {
    render(<HealthDonut parts={parts(5, 3, 2)} centerLabel="clients" ariaLabel="5 of 10 on track" caption="Clients by standing" />)
    expect(screen.getByRole('img', { name: '5 of 10 on track' })).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /Late/ })).toHaveAttribute('href', '/alerts')
  })
  it('keeps its shape with no clients and with all of them in one part', () => {
    const { rerender } = render(<HealthDonut parts={parts(0, 0, 0)} centerLabel="clients" ariaLabel="none" caption="c" />)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
    rerender(<HealthDonut parts={parts(1, 0, 0)} centerLabel="clients" ariaLabel="one" caption="c" />)
    expect(screen.getAllByText('100%').length).toBeGreaterThan(0)
  })
})

describe('CountColumns', () => {
  const col = (key: string, label: string, a: number, b: number) => ({
    key,
    label,
    parts: [
      { name: 'To sort', value: a, tone: 'watch' as const },
      { name: 'To record', value: b, tone: 'focus' as const },
    ],
  })
  it('puts the total on each column and every figure in the hidden table', () => {
    render(<CountColumns columns={[col('1', 'Client One', 5, 2), col('2', 'Client Two', 0, 3)]} ariaLabel="Work waiting on 2 clients" caption="Entries waiting" />)
    expect(screen.getByRole('img', { name: 'Work waiting on 2 clients' })).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Entries waiting' })
    expect(within(table).getByText('Client One').closest('tr')).toHaveTextContent('7')
    expect(within(table).getByText('Client Two').closest('tr')).toHaveTextContent('3')
  })
  it('still reads with one column', () => {
    render(<CountColumns columns={[col('1', 'Only Client', 4, 0)]} ariaLabel="one" caption="c" />)
    expect(screen.getAllByText('4').length).toBeGreaterThan(0)
  })
})
