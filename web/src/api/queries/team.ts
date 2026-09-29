// The team, the firm and staff work. Plain Django views, so the shapes are in api/types.ts.
//
// Everything is keyed ['team', ...] so any change to people, invites or assignments can mark all of
// it stale at once. A change to a client's lead also touches the clients list and that client.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { FirmSettings, Invite, Member, MembersResponse, MemberWork, Role, TeamClients, TeamEvent } from '@/api/types'
import { clientKeys, V1 } from './clients'

export interface DateRange {
  from: string
  to: string
}

export const teamKeys = { all: ['team'] as const }

export const teamMembers = (range?: DateRange) =>
  queryOptions({
    queryKey: [...teamKeys.all, 'members', range?.from ?? '', range?.to ?? ''],
    queryFn: () => raw.get<MembersResponse>(`${V1}/team/members/`, { from: range?.from, to: range?.to }),
  })

export const memberWork = (id: string, range: DateRange) =>
  queryOptions({
    queryKey: [...teamKeys.all, 'work', id, range.from, range.to],
    queryFn: () => raw.get<MemberWork>(`${V1}/team/members/${id}/work/`, { from: range.from, to: range.to }),
  })

export const teamClients = () =>
  queryOptions({
    queryKey: [...teamKeys.all, 'clients'],
    queryFn: () => raw.get<TeamClients>(`${V1}/team/clients/`),
  })

export const teamInvites = () =>
  queryOptions({
    queryKey: [...teamKeys.all, 'invites'],
    queryFn: () => raw.get<{ results: Invite[] }>(`${V1}/team/invites/`),
  })

export const teamEvents = () =>
  queryOptions({
    queryKey: [...teamKeys.all, 'events'],
    queryFn: () => raw.get<{ results: TeamEvent[] }>(`${V1}/team/events/`),
  })

export const firmSettings = () =>
  queryOptions({
    queryKey: ['firm', 'settings'],
    queryFn: () => raw.get<FirmSettings>(`${V1}/firm/`),
  })

/** Runs a change, then marks the team's data (and, when asked, every client's) stale. */
function useTeamMutation<V, R>(run: (v: V) => Promise<R>, { clients = false, firm = false } = {}) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: teamKeys.all }),
        clients ? queryClient.invalidateQueries({ queryKey: clientKeys.all }) : undefined,
        clients ? queryClient.invalidateQueries({ queryKey: ['client'] }) : undefined,
        firm ? queryClient.invalidateQueries({ queryKey: ['firm'] }) : undefined,
      ])
    },
  })
}

export interface InviteBody {
  email: string
  full_name?: string
  role: Role
  manager?: string | null
}

export type InviteCreated = Invite & { link: string }

export const useInvitePerson = () => useTeamMutation((body: InviteBody) => raw.post<InviteCreated>(`${V1}/team/members/`, body))

export const useRevokeInvite = () => useTeamMutation((id: string) => raw.delete(`${V1}/team/invites/${id}/`))

export interface MemberPatch {
  role?: Role
  manager?: string | null
  scope_all_clients?: boolean
  is_active?: boolean
  keep_client_assignments?: boolean
}

export const useUpdateMember = () =>
  useTeamMutation(({ id, patch }: { id: string; patch: MemberPatch }) => raw.patch<Member>(`${V1}/team/members/${id}/`, patch), {
    clients: true,
  })

export const useSetLead = () =>
  useTeamMutation(({ clientId, lead }: { clientId: string; lead: string | null }) => raw.put(`${V1}/team/clients/${clientId}/lead/`, { lead }), {
    clients: true,
  })

export const useAssign = () =>
  useTeamMutation(({ clientId, member }: { clientId: string; member: string }) => raw.post(`${V1}/team/clients/${clientId}/team/`, { member }), {
    clients: true,
  })

export const useUnassign = () =>
  useTeamMutation(({ clientId, member }: { clientId: string; member: string }) => raw.delete(`${V1}/team/clients/${clientId}/team/${member}/`), {
    clients: true,
  })

export const useRenameFirm = () => useTeamMutation((name: string) => raw.patch<{ id: string; name: string }>(`${V1}/firm/`, { name }), { firm: true })

export const useTransferOwner = () => useTeamMutation((member: string) => raw.post(`${V1}/firm/owner/`, { member }), { firm: true })
