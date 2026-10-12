import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { clientDetail, clientProfile } from '@/api/queries/clients'
import { teamClients, teamMembers } from '@/api/queries/team'
import type { Client } from '@/api/types'
import { gstRegistrations } from '@/api/queries/gst'
import { ClientTeamScreen } from './ClientTeamScreen'

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: { permissions: [] }, can: () => true }) }))

function renderIt(entries: number) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail('c1').queryKey, {
    id: 'c1',
    name: 'Divine Construwell',
    fy_start: '2025-04-01',
    lead: null,
    business_profile: 'its a construction company',
  } as unknown as Client)
  queryClient.setQueryData(clientProfile('c1').queryKey, { id: 'c1', name: 'Divine Construwell', can_edit: true, pan_shared_with: [], pan: '', tan: '', cin: '', udyam: '' } as never)
  queryClient.setQueryData(gstRegistrations('c1').queryKey, [] as never)
  queryClient.setQueryData(['client', 'c1', 'entry-count'], { count: entries, results: [] } as never)
  queryClient.setQueryData(teamClients().queryKey, {
    results: [{ id: 'c1', name: 'Divine Construwell', lead: { id: 'u1', name: 'owner_rudra' }, team: [] }],
    assignable: [],
    can: { set_lead: true },
  } as never)
  queryClient.setQueryData(teamMembers().queryKey, { leads: [{ id: 'u1', name: 'owner_rudra', role_display: 'Firm owner' }] } as never)
  render(
    <QueryClientProvider client={queryClient}>
      <ClientTeamScreen clientId="c1" justCreated={false} />
    </QueryClientProvider>,
  )
}

describe('client settings', () => {
  it('shows each fact as a row, with the year marked Locked when the client has entries', async () => {
    renderIt(3)
    expect((await screen.findAllByText('Divine Construwell')).length).toBeGreaterThan(0)
    expect(screen.getByText('its a construction company')).toBeInTheDocument()
    expect(screen.getAllByText('01-04-2025').length).toBeGreaterThan(0)
    expect(screen.getByText('Locked')).toBeInTheDocument()
    expect(screen.getByText('This client has entries, and they are numbered by financial year.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit financial year starts' })).toBeNull()
  })

  it('lets the year be edited while the client has no entries', async () => {
    renderIt(0)
    expect(await screen.findByRole('button', { name: 'Edit financial year starts' })).toBeInTheDocument()
    expect(screen.queryByText('Locked')).toBeNull()
  })

  it('edits a fact in place and puts it back on Cancel', async () => {
    renderIt(3)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit client name' }))
    const box = screen.getByRole('textbox', { name: 'Client name' })
    expect(box).toHaveValue('Divine Construwell')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.change(box, { target: { value: 'Divine Construwell Pvt Ltd' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('textbox', { name: 'Client name' })).toBeNull()
    expect(screen.getAllByText('Divine Construwell').length).toBeGreaterThan(0)
  })

  it('names the Senior CA with their role and offers Change', async () => {
    renderIt(3)
    expect(await screen.findByText('owner_rudra')).toBeInTheDocument()
    expect(screen.getByText('Firm owner')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change' })).toBeInTheDocument()
    expect(screen.getByText(/Nobody is assigned yet/)).toBeInTheDocument()
  })
})
