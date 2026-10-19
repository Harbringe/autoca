import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantStrip } from './AssistantStrip'
import type { AssistantStatus } from './queue'

const post = vi.fn()
const del = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { post: (...a: unknown[]) => post(...a), delete: (...a: unknown[]) => del(...a), get: vi.fn() } }))

let canClassify = true
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => canClassify }) }))

let status: AssistantStatus
vi.mock('./useAssistant', () => ({
  useAssistantLine: () => ({ line: status.reason === 'paused_by_person' ? 'Assistant paused: 40 rows wait until you resume it' : 'Assistant at work: 40 of 120 rows done', status }),
}))

const working: AssistantStatus = { state: 'working', reason: '', waiting: 80, total: 120, resumeAt: null }
const held: AssistantStatus = { state: 'paused', reason: 'paused_by_person', waiting: 40, total: 0, resumeAt: null }

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <AssistantStrip clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  post.mockReset().mockResolvedValue(undefined)
  del.mockReset().mockResolvedValue(undefined)
  canClassify = true
})

describe('pausing the assistant from its strip', () => {
  it('pauses while it is reading', async () => {
    status = working
    setup()
    await userEvent.click(screen.getByRole('button', { name: /pause the assistant/i }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(expect.stringContaining('/clients/c1/assistant/pause/')))
    expect(del).not.toHaveBeenCalled()
  })

  it('resumes while it is paused by a person', async () => {
    status = held
    setup()
    expect(screen.getByText(/assistant paused/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /resume the assistant/i }))
    await waitFor(() => expect(del).toHaveBeenCalledWith(expect.stringContaining('/clients/c1/assistant/pause/')))
    expect(post).not.toHaveBeenCalled()
  })

  it('offers no button to someone who may not classify rows', () => {
    canClassify = false
    status = working
    setup()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows the server’s words when it fails', async () => {
    const { ApiError } = await import('@/api/errors')
    post.mockRejectedValue(new ApiError(403, { code: 'forbidden', detail: 'You may not pause the assistant.' }))
    status = working
    setup()
    await userEvent.click(screen.getByRole('button', { name: /pause the assistant/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/may not pause/i)
  })
})
