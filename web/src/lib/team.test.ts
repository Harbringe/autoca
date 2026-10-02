import type { Member, TeamEvent } from '@/api/types'
import type { Person } from '@/api/types'
import { describeEvent, managerChoices, memberPatch } from './team'

const member = (over: Partial<Member> = {}): Member =>
  ({
    id: 'm1',
    role: 'STAFF',
    manager: { id: 's1', name: 'Sen' },
    scope_all_clients: false,
    ...over,
  }) as Member

describe('memberPatch', () => {
  const same = { role: 'STAFF' as const, manager: 's1', scopeAll: false, keepAssignments: false }
  it('sends nothing when nothing changed', () => expect(memberPatch(member(), same)).toEqual({}))
  it('sends only the role when only the role changed', () =>
    expect(memberPatch(member(), { ...same, role: 'READ_ONLY' })).toEqual({ role: 'READ_ONLY' }))
  it('moving team keeps assignments only when asked', () => {
    expect(memberPatch(member(), { ...same, manager: 's2' })).toEqual({ manager: 's2' })
    expect(memberPatch(member(), { ...same, manager: 's2', keepAssignments: true })).toEqual({
      manager: 's2',
      keep_client_assignments: true,
    })
  })
  it('does not send a team for a person who becomes a Senior CA', () =>
    expect(memberPatch(member(), { ...same, role: 'SENIOR_CA', manager: 's2' })).toEqual({ role: 'SENIOR_CA' }))
  it('sends the all-clients switch when it is flipped', () =>
    expect(memberPatch(member(), { ...same, scopeAll: true })).toEqual({ scope_all_clients: true }))
})

describe('describeEvent', () => {
  const ev = (kind: string, detail: Record<string, unknown>) =>
    ({ id: '1', kind, kind_display: 'X', detail, member_id: null, client_id: null, at: '' }) as TeamEvent
  it('says who did what to whom', () =>
    expect(describeEvent(ev('client.lead_changed', { actor: 'Asha', client: 'QA Traders', from: 'nobody', to: 'Ravi' }))).toBe(
      'Asha changed the Senior CA of QA Traders from nobody to Ravi',
    ))
  it('falls back to the kind for one it does not know', () => expect(describeEvent(ev('new.kind', { actor: 'Asha' }))).toBe('X (Asha)'))
})

describe('managerChoices', () => {
  const p = (id: string, role: Person['role'], is_owner = false) => ({ id, role, is_owner, name: id }) as Person
  const owner = p('o', 'FIRM_ADMIN', true)
  const admin = p('a', 'FIRM_ADMIN')
  const sen = p('s', 'SENIOR_CA')
  it('Staff report to a Senior CA when there is one', () => expect(managerChoices('STAFF', [owner, admin, sen])).toEqual([sen]))
  it('Staff fall back to the owner and administrators with no Senior CA', () =>
    expect(managerChoices('READ_ONLY', [owner, admin])).toEqual([owner, admin]))
  it('a Senior CA reports to an administrator, the owner included', () => expect(managerChoices('SENIOR_CA', [owner, admin, sen])).toEqual([owner, admin]))
  it('an administrator has no picker', () => expect(managerChoices('FIRM_ADMIN', [owner, admin, sen])).toEqual([]))
})
