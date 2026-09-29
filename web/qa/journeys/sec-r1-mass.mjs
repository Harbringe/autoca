import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const M = ids.members, A = ids.Alpha
const show = (l, r) => console.log(l.padEnd(58), r.status, (JSON.stringify(r.body)||'').slice(0,230))
const ad = await login('admin'), se = await login('senior'), st = await login('staff'), rd = await login('reader')
const me = (await ad.get('/api/v1/me/')).body
console.log('admin firm', me.firm.id)
const evil = { firm_id: '00000000-0000-4000-8000-0000000000aa', firm: '00000000-0000-4000-8000-0000000000aa', approved_by: M['qa.staff@autoca.test'], role: 'STAFF', is_owner: true, lead: M['qa.staff@autoca.test'], signed_off_through: '2030-01-01', created_at: '1999-01-01T00:00:00Z', id: '11111111-1111-4111-8111-111111111111', can_sign_off: false }
const c = await ad.post('/api/v1/clients/', { name: 'QA SEC Mass', fy_start: '2025-04-01', ...evil })
show('POST client + extras', c)
const cid = c.body?.id
console.log(' created id kept forced id?', cid !== evil.id, ' lead:', JSON.stringify(c.body?.lead), ' created_at:', c.body?.created_at)
show('PATCH client + extras', await ad.patch(`/api/v1/clients/${cid}/`, { business_profile: 'x', ...evil }))
const g = await ad.get(`/api/v1/clients/${cid}/`); console.log(' after: lead', JSON.stringify(g.body.lead), 'firm-visible', g.status)
const books = await ad.get(`/api/v1/clients/${cid}/books/`); console.log(' signed_off_through after extras:', books.body.signed_off_through)
// firm visible to other tenant? (only one firm testable) -- check the client shows in own firm list only
show('PUT lead + extras (admin)', await ad.put(`/api/v1/team/clients/${cid}/lead/`, { lead: M['qa.senior@autoca.test'], firm_id: evil.firm_id, role: 'FIRM_ADMIN', is_owner: true }))
show('POST team assign + extras', await ad.post(`/api/v1/team/clients/${cid}/team/`, { member: M['qa.staff@autoca.test'], role: 'FIRM_ADMIN', firm_id: evil.firm_id }))
show('POST firm/owner (admin==owner) + extras same member', await ad.post('/api/v1/firm/owner/', { member: M['qa.admin@autoca.test'], is_owner: false, role: 'STAFF' }))
show('PATCH firm + extras', await ad.patch('/api/v1/firm/', { name: me.firm.name, is_active: false, id: evil.id }))
const fm = await ad.get('/api/v1/me/'); console.log(' firm after:', fm.body.firm.name === me.firm.name, fm.body.firm.is_active, fm.body.firm.id === me.firm.id)
// lower roles on privileged team endpoints
show('senior invite FIRM_ADMIN', await se.post('/api/v1/team/members/', { email: 'qa.sec.nobody1@autoca.test', role: 'FIRM_ADMIN' }))
show('senior invite SENIOR_CA', await se.post('/api/v1/team/members/', { email: 'qa.sec.nobody2@autoca.test', role: 'SENIOR_CA' }))
show('staff invite STAFF', await st.post('/api/v1/team/members/', { email: 'qa.sec.nobody3@autoca.test', role: 'STAFF' }))
show('reader GET team/members', await rd.get('/api/v1/team/members/'))
show('staff PATCH self role FIRM_ADMIN', await st.patch(`/api/v1/team/members/${M['qa.staff@autoca.test']}/`, { role: 'FIRM_ADMIN', scope_all_clients: true, is_active: true }))
show('reader PATCH self scope_all', await rd.patch(`/api/v1/team/members/${M['qa.reader@autoca.test']}/`, { scope_all_clients: true }))
show('senior PATCH self role FIRM_ADMIN', await se.patch(`/api/v1/team/members/${M['qa.senior@autoca.test']}/`, { role: 'FIRM_ADMIN' }))
show('senior PATCH self scope_all_clients', await se.patch(`/api/v1/team/members/${M['qa.senior@autoca.test']}/`, { scope_all_clients: true }))
show('senior PATCH owner is_active=false', await se.patch(`/api/v1/team/members/${M['qa.admin@autoca.test']}/`, { is_active: false }))
show('senior PATCH staff role SENIOR_CA (not admin)', await se.patch(`/api/v1/team/members/${M['qa.staff@autoca.test']}/`, { role: 'SENIOR_CA' }))
show('senior POST firm/owner self', await se.post('/api/v1/firm/owner/', { member: M['qa.senior@autoca.test'] }))
show('senior PATCH firm rename', await se.patch('/api/v1/firm/', { name: 'QA SEC hacked' }))
show('staff GET audit', await st.get('/api/v1/audit/'))
// admin invite with extras: make_owner, role staff
const inv = await ad.post('/api/v1/team/members/', { email: 'qa.sec.nobody4@autoca.test', role: 'STAFF', make_owner: true, is_owner: true, firm_id: evil.firm_id })
show('admin invite STAFF + make_owner/is_owner/firm_id', inv)
if (inv.body?.id) show('revoke that invite', await ad.del(`/api/v1/team/invites/${inv.body.id}/`))
ids.Mass = cid
import('node:fs').then(f => f.writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(ids)))
