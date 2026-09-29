import { login, brief } from '../lib/api.mjs'
import { writeFileSync } from 'node:fs'
const a = await login('admin')
const out = {}
for (const n of ['Alpha','Beta']) {
  const name = `QA SEC ${n}`
  const list = await a.get('/api/v1/clients/', { search: name })
  let c = list.body.results.find(x => x.name === name)
  if (!c) { const r = await a.post('/api/v1/clients/', { name, fy_start: '2025-04-01' }); console.log('create', brief(r)); c = r.body }
  out[n] = c.id
}
const mem = await a.get('/api/v1/team/members/')
console.log(brief(mem).slice(0,200))
const members = mem.body.results ?? mem.body
out.members = Object.fromEntries(members.map(m => [m.email ?? m.user?.email, m.id]))
console.log(out)
writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(out))
