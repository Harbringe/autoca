import type { Member, TeamEvent } from '@/api/types'
import { describeEvent, memberPatch } from './team'

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
