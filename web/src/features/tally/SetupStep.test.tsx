import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Discovery } from '@/api/queries/tallyImport'
import { SetupStep } from './SetupStep'

const post = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
}))

const found = (over: Partial<Discovery> = {}): Discovery => ({
  vouchers: 40,
  voucher_files: 1,
  master_files: 0,
  reports: [],
  ledgers: [
    { name: 'Acme Traders', group: 'DEBTOR', reason: 'The customer on a sale', uses: 12, unsure: false },
    { name: 'Rent Paid', group: 'INDIRECT_EXPENSE', reason: 'An expense paid from the bank', uses: 3, unsure: true },
  ],
  accounts: [{ ledger: 'SBI SB A/C 62139251173', kind: 'BANK', bank_code: 'SBI', account_number: '62139251173' }],
  ...over,
})

function renderStep() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <SetupStep clientId="c1" />
    </QueryClientProvider>,
  )
}

const choose = () => fireEvent.change(screen.getByLabelText('Tally files'), { target: { files: [new File(['<x/>'], 'v.xml', { type: 'text/xml' })] } })

describe('SetupStep', () => {
  beforeEach(() => {
    post.mockReset()
  })

  it('shows what the files imply, with the reason, and flags the guesses to check', async () => {
    post.mockResolvedValueOnce(found())
    renderStep()
    choose()
    expect(await screen.findByTestId('discovery')).toHaveTextContent('40 vouchers in 1 file')
    expect(screen.getByText(/The customer on a sale/)).toBeInTheDocument()
    expect(screen.getByText(/Check this one: An expense paid from the bank/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create 2 ledgers and 1 bank account/ })).toBeEnabled()
  })

  it('creates exactly what is ticked, with the groups the person chose', async () => {
    post.mockResolvedValueOnce(found())
    post.mockResolvedValueOnce({ ledgers: 1, accounts: 1, waiting_for_a_number: [] })
    renderStep()
    choose()
    await screen.findByTestId('discovery')
    fireEvent.change(screen.getByLabelText('Group for Acme Traders'), { target: { value: 'CREDITOR' } })
    fireEvent.click(screen.getByLabelText('Rent Paid'))
    fireEvent.click(screen.getByRole('button', { name: /Create 1 ledger and 1 bank account/ }))
    expect(await screen.findByText(/1 ledger created, 1 bank account opened/)).toBeInTheDocument()
    expect(post).toHaveBeenLastCalledWith('/api/v1/clients/c1/tally-imports/setup/', {
      ledgers: [{ name: 'Acme Traders', group: 'CREDITOR' }],
      accounts: [{ ledger: 'SBI SB A/C 62139251173', kind: 'BANK', bank_code: 'SBI', account_number: '62139251173' }],
    })
  })

  it('asks which bank ledger a report is for when the file name does not say, and reads again with the answer', async () => {
    post.mockResolvedValueOnce(found({ reports: [{ file: 'bank.xml', ledger: '', rows: 34, left_out: 15 }] }))
    post.mockResolvedValueOnce(found({ reports: [{ file: 'bank.xml', ledger: 'Bank', rows: 34, left_out: 15 }] }))
    renderStep()
    choose()
    await screen.findByTestId('discovery')
    fireEvent.change(screen.getByLabelText('Bank ledger of bank.xml'), { target: { value: 'Bank' } })
    fireEvent.click(screen.getByRole('button', { name: 'Read again' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    const form = post.mock.calls[1]![1] as FormData
    expect(form.get('bank_ledgers')).toBe(JSON.stringify({ 'bank.xml': 'Bank' }))
  })

  it("shows the server's words when a file is refused", async () => {
    post.mockRejectedValueOnce(new Error('bank.xml is not an .xml file exported from Tally.'))
    renderStep()
    choose()
    expect(await screen.findByRole('alert')).toHaveTextContent('not an .xml file')
  })
})
