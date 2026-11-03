import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { clientDetail } from '@/api/queries/clients'
import type { Client } from '@/api/types'
import { PayrollScreen } from './PayrollScreen'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), blob: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const page = (results: object[]) => ({ results, next: null, count: results.length })

function show() {
  vi.mocked(raw.get).mockImplementation(((url: string) => {
    if (url.endsWith('/employees/')) return Promise.resolve(page([{ id: 'e1', name: 'Asha', is_active: true, ledger: null }]))
    if (url.endsWith('/payroll/')) return Promise.resolve(page([]))
    if (url.includes('/pf-esi/')) return Promise.resolve({ year: 2026, month: 10, has_run: false, due: '2026-11-15' })
    return Promise.resolve({ id: 'c1', can_post: true })
  }) as never)
  vi.mocked(raw.post).mockResolvedValue({})
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme', can_post: true } as unknown as Client)
  render(
    <QueryClientProvider client={queryClient}>
      <PayrollScreen clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('PayrollScreen', () => {
  it('sends the PF wages typed on a salary line, and none when the box is left empty', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Gross for Asha'), '40000')
    await userEvent.type(screen.getByLabelText('PF (employee) for Asha'), '1800')
    await userEvent.type(screen.getByLabelText('PF wages for Asha'), '18000')
    await userEvent.click(screen.getByRole('button', { name: 'Book salaries' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalled())
    expect(vi.mocked(raw.post).mock.calls[0]?.[1]).toMatchObject({ lines: [expect.objectContaining({ pf_wages_paise: 1_800_000 })] })

    vi.mocked(raw.post).mockClear()
    await userEvent.type(screen.getByLabelText('Gross for Asha'), '40000')
    await userEvent.click(screen.getByRole('button', { name: 'Book salaries' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalled())
    expect(vi.mocked(raw.post).mock.calls[0]?.[1]).toMatchObject({ lines: [expect.objectContaining({ pf_wages_paise: null })] })
  })

  it('adds an employee when Enter is pressed in the name box', async () => {
    show()
    await userEvent.type(await screen.findByLabelText('Employee name'), 'Bhanu{Enter}')
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith(expect.stringContaining('/employees/'), expect.anything()))
  })
})
