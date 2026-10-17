import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { bankAccounts } from '@/api/queries/clients'
import { BankReportStep } from './BankReportStep'

const post = vi.fn()
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
}))

function renderStep(onStaged = vi.fn(), onError = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false }, mutations: { retry: false } } })
  queryClient.setQueryData(bankAccounts('c1').queryKey, { results: [{ id: 'a1', ledger_name: 'SBI SB A/C 1173' }, { id: 'a2', ledger_name: 'SBI CC A/C 3596' }] } as never)
  render(
    <QueryClientProvider client={queryClient}>
      <BankReportStep clientId="c1" onStaged={onStaged} onError={onError} />
    </QueryClientProvider>,
  )
  return { onStaged, onError }
}

const files = (...names: string[]) =>
  fireEvent.change(screen.getByLabelText('Bank reports'), { target: { files: names.map((n) => new File(['<x/>'], n, { type: 'text/xml' })) } })

describe('BankReportStep', () => {
  beforeEach(() => {
    post.mockReset()
  })

  it('cannot preview until every report has its own account', async () => {
    renderStep()
    files('a.xml', 'b.xml')
    const preview = await screen.findByRole('button', { name: /Preview the bank entries/ })
    expect(preview).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Bank account for a.xml'), { target: { value: 'a1' } })
    fireEvent.change(screen.getByLabelText('Bank account for b.xml'), { target: { value: 'a1' } })
    expect(preview).toBeDisabled() // the same account twice
    fireEvent.change(screen.getByLabelText('Bank account for b.xml'), { target: { value: 'a2' } })
    expect(preview).toBeEnabled()
  })

  it('sends each report with its account and hands the preview on', async () => {
    post.mockResolvedValueOnce({ id: 'r9', status: 'PREVIEW' })
    const { onStaged } = renderStep()
    files('a.xml')
    fireEvent.change(await screen.findByLabelText('Bank account for a.xml'), { target: { value: 'a1' } })
    fireEvent.click(screen.getByRole('button', { name: /Preview the bank entries/ }))
    await waitFor(() => expect(onStaged).toHaveBeenCalledWith({ id: 'r9', status: 'PREVIEW' }))
    const form = post.mock.calls[0]![1] as FormData
    expect(form.getAll('accounts')).toEqual(['a1'])
    expect((form.getAll('files')[0] as File).name).toBe('a.xml')
  })

  it("passes the server's words on when the reports are refused", async () => {
    post.mockRejectedValueOnce(new Error('Two reports are for SBI SB A/C 1173.'))
    const { onError } = renderStep()
    files('a.xml')
    fireEvent.change(await screen.findByLabelText('Bank account for a.xml'), { target: { value: 'a1' } })
    fireEvent.click(screen.getByRole('button', { name: /Preview the bank entries/ }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Two reports are for SBI SB A/C 1173.'))
  })
})
