import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const B = ids.Beta
const show = (l, r) => console.log(l.padEnd(46), r.status, (JSON.stringify(r.body)||'').slice(0,200))
const se = await login('senior'), ad = await login('admin'), st = await login('staff')
show('admin set Beta lead=admin', await ad.put(`/api/v1/team/clients/${B}/lead/`, { lead: ids.members['qa.admin@autoca.test'] }))
show('senior sign-off Beta (member, lead=admin)', await se.post(`/api/v1/clients/${B}/books/sign-off/`, {}))
show('senior reopen Beta', await se.post(`/api/v1/clients/${B}/books/reopen/`, {note:'x'}))
show('senior set lead Beta (self)', await se.put(`/api/v1/team/clients/${B}/lead/`, { lead: ids.members['qa.senior@autoca.test'] }))
show('staff set lead Alpha (self)', await st.put(`/api/v1/team/clients/${ids.Alpha}/lead/`, { lead: ids.members['qa.staff@autoca.test'] }))
show('staff assign self Beta', await st.post(`/api/v1/team/clients/${B}/team/`, { member: ids.members['qa.staff@autoca.test'] }))
show('senior assign staff to Beta (not lead)', await se.post(`/api/v1/team/clients/${B}/team/`, { member: ids.members['qa.staff@autoca.test'] }))
show('senior GET team/clients', await se.get(`/api/v1/team/clients/`))
