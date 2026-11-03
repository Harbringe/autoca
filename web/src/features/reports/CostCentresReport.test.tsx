import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { CostCentresReport } from './CostCentresReport'

vi.mock('@/api/client', () => ({ raw: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

beforeEach(() => vi.clearAllMocks())

describe('CostCentresReport', () => {
  it('adds a cost centre when Enter is pressed in the name box', async () => {
    vi.mocked(raw.get).mockResolvedValue({ centres: [], untagged: { income_paise: 0, expense_paise: 0 } })
    vi.mocked(raw.post).mockResolvedValue({})
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CostCentresReport clientId="c1" fy={2026} />
      </QueryClientProvider>,
    )
    await userEvent.type(await screen.findByLabelText('Cost centre name'), 'Pune site{Enter}')
    await waitFor(() => expect(raw.post).toHaveBeenCalledWith(expect.stringContaining('/cost-centres/'), expect.anything()))
  })
})
