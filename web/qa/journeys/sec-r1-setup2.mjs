import { login, brief } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const M = ids.members
const a = await login('admin')
console.log('lead Alpha=senior', brief(await a.put(`/api/v1/team/clients/${ids.Alpha}/lead/`, { lead: M['qa.senior@autoca.test'] })))
console.log('assign staff Alpha', brief(await a.post(`/api/v1/team/clients/${ids.Alpha}/team/`, { member: M['qa.staff@autoca.test'] })))
console.log('assign senior Beta (member)', brief(await a.post(`/api/v1/team/clients/${ids.Beta}/team/`, { member: M['qa.senior@autoca.test'] })))
for (const n of ['Alpha','Beta']) {
  const r = await a.upload(`/api/v1/clients/${ids[n]}/statements/upload/`, `qa/samples/qa-sec-${n.toLowerCase()}-2025-04.pdf`)
  console.log('upload', n, r.status, JSON.stringify(r.body).slice(0,300))
  const job = await a.job(r); console.log(job.status, JSON.stringify(job.result ?? job.error ?? '').slice(0,300))
}
for (const n of ['Alpha','Beta']) {
  const ba = await a.get(`/api/v1/clients/${ids[n]}/bank-accounts/`)
  const st = await a.get(`/api/v1/clients/${ids[n]}/statements/`)
  const tx = await a.get('/api/v1/transactions/', { client: ids[n], page_size: 3 })
  const led = await a.get(`/api/v1/clients/${ids[n]}/ledgers/`, {page_size:5})
  const rq = await a.get(`/api/v1/clients/${ids[n]}/review-queue/`, {page_size:3})
  ids[n+'_ba'] = ba.body.results?.[0]?.id; ids[n+'_st'] = st.body.results?.[0]?.id
  ids[n+'_tx'] = tx.body.results?.[0]?.id; ids[n+'_led'] = led.body.results?.[0]?.id
  console.log(n, ba.status, st.status, tx.status, led.status, rq.status, JSON.stringify(rq.body).slice(0,500))
  ids[n+'_rq'] = rq.body.results?.[0]
}
writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(ids))
console.log(ids)
