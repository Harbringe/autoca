import { login, brief } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const a = await login('admin')
for (const n of ['Alpha','Beta']) {
  const ba = await a.get(`/api/v1/clients/${ids[n]}/bank-accounts/`)
  const st = await a.get(`/api/v1/clients/${ids[n]}/statements/`)
  const tx = await a.get('/api/v1/transactions/', { client: ids[n], page_size: 3 })
  const led = await a.get(`/api/v1/clients/${ids[n]}/ledgers/`, {page_size:5})
  const rq = await a.get(`/api/v1/clients/${ids[n]}/review-queue/`, {page_size:3})
  console.log(n, ba.status, st.status, tx.status, led.status, rq.status)
  ids[n+'_ba'] = ba.body.results?.[0]?.id; ids[n+'_st'] = st.body.results?.[0]?.id
  ids[n+'_tx'] = tx.body.results?.[0]?.id; ids[n+'_led'] = led.body.results?.[0]?.id
  ids[n+'_rq'] = rq.body.results?.[0]
  console.log(JSON.stringify(rq.body).slice(0,700))
}
writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(ids))
console.log(JSON.stringify(ids,null,1))
