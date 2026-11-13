import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import type { MembersResponse } from '@/api/types'
import { BulkInviteDialog } from './BulkInviteDialog'

vi.mock('@/api/client', async (original) => {
  const actual = await original<typeof import('@/api/client')>()
  return { ...actual, raw: { ...actual.raw, post: vi.fn(), get: vi.fn() } }
})

const info = { can: { invite: true, manage: false, invite_roles: ['STAFF', 'READ_ONLY'] }, leads: [], results: [] } as unknown as MembersResponse

function open() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <BulkInviteDialog open onOpenChange={() => {}} info={info} />
    </QueryClientProvider>,
  )
}

const paste = (text: string) => fireEvent.change(screen.getByLabelText('Email addresses'), { target: { value: text } })

describe('BulkInviteDialog', () => {
  beforeEach(() => {
    vi.mocked(raw.post).mockReset()
  })

  it('says what it read and what it skipped before anything is sent', () => {
    open()
    paste('a@firm.test\nBea Rao <b@firm.test>, Read only\nnot an address')
    expect(screen.getByRole('status')).toHaveTextContent('2 people read, 1 skipped')
    expect(screen.getByRole('status')).toHaveTextContent('Line 3: No email address on this line.')
    expect(screen.getByRole('button', { name: 'Create 2 invitations' })).toBeEnabled()
  })

  it('sends every row with the role it asked for, or the one chosen for everyone else', async () => {
    vi.mocked(raw.post).mockResolvedValue({ results: [] } as never)
    open()
    paste('a@firm.test\nBea Rao <b@firm.test>, Read only')
    fireEvent.click(screen.getByRole('button', { name: 'Create 2 invitations' }))
    await waitFor(() => expect(raw.post).toHaveBeenCalled())
    expect(raw.post).toHaveBeenCalledWith('/api/v1/team/members/bulk/', {
      rows: [
        { email: 'a@firm.test', full_name: undefined, role: 'STAFF', manager: undefined },
        { email: 'b@firm.test', full_name: 'Bea Rao', role: 'READ_ONLY', manager: undefined },
      ],
    })
  })

  it('shows each row’s own answer, with a link to copy for the ones that worked and the reason for the ones that did not', async () => {
    vi.mocked(raw.post).mockResolvedValue({
      results: [
        { email: 'a@firm.test', ok: true, link: 'https://app.test/invite/x.y', role_display: 'Staff' },
        { email: 'b@firm.test', ok: false, error: 'b@firm.test is already in the firm.' },
      ],
    } as never)
    open()
    paste('a@firm.test\nb@firm.test')
    fireEvent.click(screen.getByRole('button', { name: 'Create 2 invitations' }))
    expect(await screen.findByRole('button', { name: 'Copy the link for a@firm.test' })).toBeInTheDocument()
    expect(screen.getByText('b@firm.test is already in the firm.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy all links' })).toBeInTheDocument()
    expect(screen.getByText(/shown only now/)).toBeInTheDocument()
  })

  it('refuses more than fifty people without asking the server', () => {
    open()
    paste(Array.from({ length: 51 }, (_, i) => `p${i}@firm.test`).join('\n'))
    fireEvent.click(screen.getByRole('button', { name: 'Create 51 invitations' }))
    expect(screen.getByRole('alert')).toHaveTextContent('50 people at a time at most')
    expect(raw.post).not.toHaveBeenCalled()
  })

  it('keeps the create button off until there is something to send', () => {
    open()
    expect(screen.getByRole('button', { name: 'Create invitations' })).toBeDisabled()
  })
})
