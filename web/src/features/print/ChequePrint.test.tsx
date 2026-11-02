import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { ChequePrint } from './ChequePrint'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn() } }))

describe('ChequePrint', () => {
  it('lays out the date in boxes, the payee, the amount in words and figures, and can drop the crossing', async () => {
    vi.mocked(raw.get).mockImplementation(((url: string) =>
      Promise.resolve(url.includes('/cheques/') ? { id: 'q1', number: '000101', cheque_date: '2026-12-01', amount_paise: 12345000, print_name: 'Sharma Traders' } : { name: 'Acme Traders' })) as never)
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ChequePrint clientId="c1" chequeId="q1" />
      </QueryClientProvider>,
    )
    expect(await screen.findByLabelText('Payee')).toHaveTextContent('Sharma Traders')
    expect(screen.getByLabelText('Date')).toHaveTextContent('01122026')
    expect(screen.getByLabelText('Amount in words')).toHaveTextContent('Rupees One Lakh Twenty Three Thousand Four Hundred Fifty Only')
    expect(screen.getByLabelText('Amount in figures')).toHaveTextContent('1,23,450.00')
    expect(screen.getByLabelText('Crossing')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('A/C Payee only'))
    expect(screen.queryByLabelText('Crossing')).not.toBeInTheDocument()
  })
})
