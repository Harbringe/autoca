import { login } from '../lib/api.mjs'
import { writeFileSync } from 'node:fs'

const admin = await login('admin')
const clients = await admin.all('api/v1/clients/')
let mine = clients.find(c => c.name === 'QA SCA Kapoor Textiles')
if (!mine) {
  const r = await admin.post('api/v1/clients/', {
    name: 'QA SCA Kapoor Textiles',
    fy_start: '2025-04-01',
  })
  console.log('create client', r.status, JSON.stringify(r.body).slice(0,400))
  mine = r.body
} else {
  console.log('reusing client', mine.id)
}

const leadR = await admin.put(`api/v1/team/clients/${mine.id}/lead/`, { lead: null })
console.log('lead lookup(noop)', leadR.status)

// list members to find senior/staff ids
const members = await admin.all('api/v1/team/members/')
console.log('members', members.map(m => `${m.id}:${m.email ?? m.name ?? ''}:${m.role}`))

writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json', JSON.stringify({ client: mine }, null, 2))
console.log('serverErrors', admin.serverErrors())
