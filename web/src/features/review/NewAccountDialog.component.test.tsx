import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import type { LedgerAccount } from '@/api/types'
import { NewAccountDialog } from './NewAccountDialog'

vi.mock('@/api/client', () => ({ raw: { post: vi.fn() } }))

const ledger = (id: string, name: string, group: string) => ({ id, name, group, status: 'ACTIVE', is_active: true }) as unknown as LedgerAccount

function open(props: Partial<React.ComponentProps<typeof NewAccountDialog>> = {}) {
  const onCreated = vi.fn()
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NewAccountDialog clientId="c1" ledgers={[ledger('l1', 'Courier Charges', 'INDIRECT_EXPENSE')]} onCreated={onCreated} onClose={onClose} {...props} />
    </QueryClientProvider>,
  )
  return { onCreated, onClose }
}

describe('Creating an account', () => {
  it('says what the kind of account is for and where it will show', async () => {
    open()
    expect(screen.getByText(/Running costs: rent, salaries/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('What kind of account is it?'), 'DEBTOR')
    expect(screen.getByText(/A customer or anyone who owes you money/)).toBeInTheDocument()
    expect(screen.getByText(/Balance Sheet, under receivables/)).toBeInTheDocument()
  })

  it('warns about a similar account and refuses an exact repeat', async () => {
    open()
    await userEvent.type(screen.getByLabelText('Account name'), 'Courier')
    expect(screen.getByRole('status')).toHaveTextContent('A similar account already exists: Courier Charges')
    await userEvent.clear(screen.getByLabelText('Account name'))
    await userEvent.type(screen.getByLabelText('Account name'), 'courier charges')
    expect(screen.getByRole('status')).toHaveTextContent('There is already an account called')
    expect(screen.getByRole('button', { name: 'Create and use' })).toBeDisabled()
  })

  it('creates the account under the chosen kind and hands it back', async () => {
    vi.mocked(raw.post).mockResolvedValue(ledger('l9', 'Packing Material', 'DIRECT_EXPENSE'))
    const { onCreated } = open({ initialName: 'Packing Material' })
    await userEvent.selectOptions(screen.getByLabelText('What kind of account is it?'), 'DIRECT_EXPENSE')
    await userEvent.click(screen.getByRole('button', { name: 'Create and use' }))
    expect(raw.post).toHaveBeenCalledWith(expect.stringContaining('/clients/c1/ledgers/'), { name: 'Packing Material', group: 'DIRECT_EXPENSE' })
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'l9' }))
  })

  it('offers Bank Accounts for another bank account and Suspense, and creates them under those groups', async () => {
    vi.mocked(raw.post).mockResolvedValue(ledger('l8', 'SBI SB A/C 62139251173', 'BANK'))
    open({ initialName: 'SBI SB A/C 62139251173' })
    const kind = screen.getByLabelText('What kind of account is it?')
    expect(screen.getByRole('option', { name: 'Bank Accounts' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Suspense A/c' })).toBeInTheDocument()
    await userEvent.selectOptions(kind, 'BANK')
    expect(screen.getByText(/another bank that you do not upload statements for/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create and use' }))
    expect(raw.post).toHaveBeenCalledWith(expect.stringContaining('/clients/c1/ledgers/'), { name: 'SBI SB A/C 62139251173', group: 'BANK' })
    await userEvent.selectOptions(kind, 'SUSPENSE')
    expect(screen.getByText(/cleared to nil before the books are signed off/)).toBeInTheDocument()
  })

  it('offers every group the books know', () => {
    open()
    const offered = screen.getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(offered.sort()).toEqual(
      ['BANK', 'CAPITAL', 'CASH', 'CREDITOR', 'DEBTOR', 'DIRECT_EXPENSE', 'DIRECT_INCOME', 'DUTIES_AND_TAXES', 'INDIRECT_EXPENSE', 'INDIRECT_INCOME', 'INVESTMENT', 'LOAN', 'SUSPENSE'].sort(),
    )
  })

  // The groups the assistant may suggest (classify/standard_ledgers.py, SUGGESTABLE_GROUPS) must all be offered here, or a suggestion
  // would quietly turn into Indirect Expense. Keep this list and that one the same.
  it.each([
    'INDIRECT_EXPENSE', 'DIRECT_EXPENSE', 'INDIRECT_INCOME', 'DIRECT_INCOME', 'CREDITOR', 'DEBTOR', 'LOAN', 'DUTIES_AND_TAXES', 'INVESTMENT', 'CAPITAL',
  ])('offers %s, so a suggestion in that group is not changed to another', (group) => {
    open({ initialName: 'Dividend Received', initialGroup: group })
    expect(screen.getByLabelText('What kind of account is it?')).toHaveValue(group)
  })
})
