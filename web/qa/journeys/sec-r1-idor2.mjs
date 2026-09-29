import { login, brief } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const a = await login('admin')
const pick = ids.Beta_cls.find(c => c.ledger && !c.posted)
const ap = await a.post(`/api/v1/clients/${ids.Beta}/approvals/`, { classifications: [pick.id] })
console.log('admin approve beta', brief(ap))
ids.Beta_je = ap.body?.[0]?.id
console.log('JE', ids.Beta_je, JSON.stringify(ap.body?.[0]).slice(0,300))
writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(ids))
