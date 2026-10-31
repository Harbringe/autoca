import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { VoucherRunSummary } from '@/api/queries/tallyImport'
import { MoveProgress } from './MoveProgress'

const run = (id: string, dateFrom: string, over: Partial<VoucherRunSummary> = {}): VoucherRunSummary => ({
  id,
  status: 'PREVIEW',
  financial_year: 2025,
  expires_at: '2099-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  file_name: 'year.xml',
  document: 'd1',
  uploaded_by_name: 'Asha',
  posting: false,
  progress: null,
  error: '',
  result: null,
  counts: { vouchers: 5, will_post: 5, will_make_bill: 0, skipped: 0, bank_waiting: 0, bank_rows: 0, stock_lines: 0, by_type: {}, date_from: dateFrom, date_to: dateFrom },
  ...over,
})

describe('MoveProgress', () => {
  it('counts the months of each financial year by where they are', () => {
    render(
      <MoveProgress
        runs={[
          run('a', '2025-04-01'),
          run('b', '2025-05-01'),
          run('c', '2025-03-01', { status: 'CONFIRMED' }),
          run('d', '2025-06-01', { posting: true, progress: { done: 1, total: 5 } }),
        ]}
      />,
    )
    expect(screen.getByText('FY 2025-26')).toBeInTheDocument()
    expect(screen.getByText('FY 2024-25')).toBeInTheDocument()
    expect(screen.getByTestId('fy-2025')).toHaveTextContent('2 waiting')
    expect(screen.getByTestId('fy-2025')).toHaveTextContent('1 posting')
    expect(screen.getByTestId('fy-2024')).toHaveTextContent('1 posted')
  })

  it('says nothing has been read yet when the queue is empty', () => {
    render(<MoveProgress runs={[]} />)
    expect(screen.getByText(/Nothing has been read yet/)).toBeInTheDocument()
  })

  it('leaves discarded imports out', () => {
    render(<MoveProgress runs={[run('a', '2025-04-01', { status: 'DISCARDED' })]} />)
    expect(screen.queryByText('FY 2025-26')).not.toBeInTheDocument()
  })
})
