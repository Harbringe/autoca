// The rules of the team screens that are logic rather than layout.

import type { Member, Person, Role, TeamEvent } from '@/api/types'
import type { MemberPatch } from '@/api/queries/team'

/** Staff and Read-only members sit on a Senior CA's team; the others lead or administer. */
export const isTeamRole = (role: Role) => role === 'STAFF' || role === 'READ_ONLY'

/**
 * Who a person of this role may report to. A Senior CA reports to an administrator (the owner is one).
 * Staff and Read-only report to a Senior CA, and fall back to the owner or an administrator
 * when the firm has no Senior CA. Administrators have no manager picker.
 */
export function managerChoices(role: Role, people: Person[]): Person[] {
  if (role === 'SENIOR_CA') return people.filter((p) => p.role === 'FIRM_ADMIN')
  if (!isTeamRole(role)) return []
  const seniors = people.filter((p) => p.role === 'SENIOR_CA')
  return seniors.length ? seniors : people.filter((p) => p.role === 'FIRM_ADMIN')
}

export function managerHint(role: Role, choices: Person[]): string {
  if (role === 'SENIOR_CA') return 'Senior CAs report to an administrator.'
  return choices.some((p) => p.role === 'FIRM_ADMIN')
    ? 'The firm has no Senior CA yet, so they report to the owner or an administrator.'
    : 'Staff and Read-only members report to a Senior CA.'
}

export interface MemberEdit {
  role: Role
  manager: string | null
  scopeAll: boolean
  keepAssignments: boolean
}

/** Only what changed, so the server is asked for nothing it has not been told to do. */
export function memberPatch(member: Member, edit: MemberEdit): MemberPatch {
  const patch: MemberPatch = {}
  if (edit.role !== member.role) patch.role = edit.role
  const managerBefore = member.manager?.id ?? null
  // Leaders and administrators have no team; the server clears it when the role becomes one of those.
  if (isTeamRole(edit.role) && edit.manager !== managerBefore) {
    patch.manager = edit.manager
    if (managerBefore && edit.keepAssignments) patch.keep_client_assignments = true
  }
  if (edit.role !== 'FIRM_ADMIN' && edit.scopeAll !== member.scope_all_clients) patch.scope_all_clients = edit.scopeAll
  return patch
}

const text = (v: unknown) => (typeof v === 'string' && v ? v : 'nobody')

/** One line of the team's history, from the names the server recorded at the time. */
export function describeEvent(e: TeamEvent): string {
  const d = e.detail ?? {}
  const actor = text(d.actor)
  switch (e.kind) {
    case 'member.invited':
      return `${actor} invited ${text(d.email)} as ${text(d.role)}${d.to ? ` to ${text(d.to)}’s team` : ''}`
    case 'member.joined':
      return `${text(d.member)} joined as ${text(d.role)}`
    case 'invite.revoked':
      return `${actor} revoked the invite to ${text(d.email)}`
    case 'member.role_changed':
      return `${actor} changed ${text(d.member)} from ${text(d.from)} to ${text(d.to)}`
    case 'firm.owner_changed':
      return `${actor} made ${text(d.to)} the firm owner (was ${text(d.from)})`
    case 'firm.renamed':
      return `${actor} renamed the firm from ${text(d.from)} to ${text(d.to)}`
    case 'member.manager_changed':
      return `${actor} moved ${text(d.member)} from ${text(d.from)}’s team to ${text(d.to)}’s`
    case 'member.scope_changed':
      return `${actor} turned access to every client ${text(d.to)} for ${text(d.member)}`
    case 'member.deactivated':
      return `${actor} deactivated ${text(d.member)}`
    case 'member.reactivated':
      return `${actor} reactivated ${text(d.member)}`
    case 'member.removed':
      return `${text(d.member)} was removed from the firm`
    case 'client.lead_changed':
      return `${actor} changed the Senior CA of ${text(d.client)} from ${text(d.from)} to ${text(d.to)}`
    case 'client.assigned':
      return `${actor} put ${text(d.member)} on ${text(d.client)}`
    case 'client.unassigned':
      return `${actor} took ${text(d.member)} off ${text(d.client)}`
    default:
      return `${e.kind_display} (${actor})`
  }
}
