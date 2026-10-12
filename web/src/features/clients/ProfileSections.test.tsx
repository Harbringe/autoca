import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { raw } from '@/api/client'
import { clientDetail, clientProfile } from '@/api/queries/clients'
import { gstRegistrations } from '@/api/queries/gst'
import type { Client } from '@/api/types'
import { ProfileHeader, ProfileSections } from './ProfileSections'

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  raw: { patch: vi.fn(async (_path: string, body: object) => ({ ...profile, ...body })), get: vi.fn() },
}))

const profile = {
  id: 'c1',
  name: 'Acme Traders',
  trade_name: 'Acme',
  constitution: 'PRIVATE_LIMITED',
  msme_category: 'SMALL',
  client_since: '2021-04-01',
  incorporated_on: null,
  address: '',
  contact_name: 'Meera Shah',
  contact_email: '',
  contact_phone: '',
  contact2_name: '',
  contact2_email: '',
  contact2_phone: '',
  notes: '',
  pan: 'ABCDE1234F',
  tan: '',
  cin: '',
  udyam: '',
  pan_shared_with: ['Other Traders'],
  can_edit: true,
  profile_updated_at: '2026-10-11T10:00:00Z',
  profile_updated_by: 'owner_rudra',
}

function renderIt(over: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, { id: 'c1', name: 'Acme Traders', fy_start: '2025-04-01' } as unknown as Client)
  queryClient.setQueryData(clientProfile('c1').queryKey, { ...profile, ...over } as never)
  queryClient.setQueryData(gstRegistrations('c1').queryKey, [] as never)
  render(
    <QueryClientProvider client={queryClient}>
      <ProfileHeader clientId="c1" />
      <ProfileSections clientId="c1" />
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.mocked(raw.patch).mockClear())

describe('the client profile', () => {
  it('shows who the client is at a glance', async () => {
    renderIt()
    expect(await screen.findByText('Trades as Acme')).toBeInTheDocument()
    expect(screen.getAllByText('Private limited company').length).toBeGreaterThan(0)
    expect(screen.getByText(/MSME · Small/)).toBeInTheDocument()
    expect(screen.getByText(/Profile last edited 11-10-2026 by owner_rudra/)).toBeInTheDocument()
  })

  it('warns when another client carries the same PAN', async () => {
    renderIt()
    expect(await screen.findByText(/also on Other Traders/)).toBeInTheDocument()
  })

  it('shows what is missing as Not added', async () => {
    renderIt()
    expect((await screen.findAllByText('Not added')).length).toBeGreaterThan(3)
  })

  it('edits a section, sending only what changed, with a date as ISO', async () => {
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit contacts and address' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Phone' }), { target: { value: '98200 12345' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(raw.patch).toHaveBeenCalledWith('/api/v1/clients/c1/profile/', { contact_phone: '98200 12345' }))
  })

  it('sends a typed date as ISO', async () => {
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit about the client' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Incorporated or started on' }), { target: { value: '15-06-2019' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(raw.patch).toHaveBeenCalledWith('/api/v1/clients/c1/profile/', { incorporated_on: '2019-06-15' }))
  })

  it('names a date it cannot read and sends nothing', async () => {
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit about the client' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Incorporated or started on' }), { target: { value: 'soon' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorporated or started on')
    expect(raw.patch).not.toHaveBeenCalled()
  })

  it('offers no Edit buttons to someone who may not edit', async () => {
    renderIt({ can_edit: false, pan: 'AB*******F' })
    expect(await screen.findByText('AB*******F')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit / })).toBeNull()
  })
})
