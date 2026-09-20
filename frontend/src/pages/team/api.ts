// Teams: people, who leads what, who works on what, and how much got done.

import { api, V1 } from '../../api/client'

export const TEAM = `${V1}/team`

export interface Person {
  id: string
  name: string
  role: string
  role_display: string
  is_owner: boolean
  is_active: boolean
}

export interface ClientRef {
  id: string
  name: string
  how: 'assigned' | 'leads'
}

export interface Metric {
  key: string
  label: string
}

export interface Member extends Person {
  user_id: string
  email: string
  full_name: string
  scope_all_clients: boolean
  manager: Person | null
  last_login: string | null
  created_at: string
  is_me: boolean
  clients: ClientRef[]
  can: { manage: boolean; set_active: boolean }
  work: Record<string, number>
}

export interface MembersPage {
  period: { from: string; to: string }
  metrics: Metric[]
  can: { invite: boolean; invite_roles: string[]; manage: boolean; manage_admins: boolean }
  leads: Person[]
  results: Member[]
}

export interface TeamClient {
  id: string
  name: string
  lead: Person | null
  team: (Person & { assigned_at: string; on_my_team: boolean })[]
  unresolved: number
  pending_approval: number
}

export interface ClientsPage {
  can: { set_lead: boolean }
  assignable: Person[]
  results: TeamClient[]
}

export interface WorkReport {
  member: Person
  period: { from: string; to: string }
  metrics: Metric[]
  totals: Record<string, number>
  by_client: ({ id: string | null; name: string } & Record<string, number | string | null>)[]
  by_day: { date: string; count: number }[]
  open_work: { id: string; name: string; unresolved: number; pending_approval: number }[]
}

export interface Invite {
  id: string
  email: string
  full_name: string
  role: string
  role_display: string
  manager: Person | null
  expires_at: string
  created_at: string
  created_by: string | null
  link?: string
}

export interface TeamEvent {
  id: string
  kind: string
  kind_display: string
  detail: Record<string, string | number>
  at: string
}

export const ROLE_LABELS: Record<string, string> = {
  FIRM_ADMIN: 'Firm administrator',
  SENIOR_CA: 'Senior CA',
  STAFF: 'Staff',
  READ_ONLY: 'Read only',
}

export type Range = { from: string; to: string }

function iso(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

export const RANGES: { key: string; label: string; range: () => Range }[] = [
  {
    key: 'week',
    label: 'Last 7 days',
    range: () => ({ from: iso(new Date(Date.now() - 6 * 86400000)), to: iso(new Date()) }),
  },
  {
    key: 'month',
    label: 'Last 30 days',
    range: () => ({ from: iso(new Date(Date.now() - 29 * 86400000)), to: iso(new Date()) }),
  },
  {
    key: 'this-month',
    label: 'This month',
    range: () => {
      const now = new Date()
      return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)), to: iso(now) }
    },
  },
  {
    key: 'quarter',
    label: 'Last 90 days',
    range: () => ({ from: iso(new Date(Date.now() - 89 * 86400000)), to: iso(new Date()) }),
  },
]

const q = (range: Range) => `from=${range.from}&to=${range.to}`

export const teamApi = {
  members: (range: Range) => api.get<MembersPage>(`${TEAM}/members/?${q(range)}`),
  update: (id: string, body: Record<string, unknown>) => api.patch<Member>(`${TEAM}/members/${id}/`, body),
  invite: (body: { email: string; full_name: string; role: string; manager?: string | null }) =>
    api.post<Invite & { link: string }>(`${TEAM}/members/`, body),
  work: (id: string, range: Range) => api.get<WorkReport>(`${TEAM}/members/${id}/work/?${q(range)}`),
  clients: () => api.get<ClientsPage>(`${TEAM}/clients/`),
  setLead: (clientId: string, lead: string | null) => api.put(`${TEAM}/clients/${clientId}/lead/`, { lead }),
  assign: (clientId: string, member: string) => api.post(`${TEAM}/clients/${clientId}/team/`, { member }),
  unassign: (clientId: string, member: string) => api.delete(`${TEAM}/clients/${clientId}/team/${member}/`),
  invites: () => api.get<{ results: Invite[] }>(`${TEAM}/invites/`),
  revokeInvite: (id: string) => api.delete(`${TEAM}/invites/${id}/`),
  events: () => api.get<{ results: TeamEvent[] }>(`${TEAM}/events/`),
}
