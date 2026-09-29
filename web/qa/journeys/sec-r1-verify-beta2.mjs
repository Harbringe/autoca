import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const a = await login('admin')
const ch = await a.get(`/api/v1/journal-entries/${ids.Beta_je}/changes/`)
console.log(ch.body.map(x => ({ action: x.action, by: x.by ?? x.actor ?? x.changed_by ?? Object.keys(x).join(','), at: x.created_at ?? x.at })))
const r = await a.get(`/api/v1/clients/${ids.Beta}/rules/`)
console.log('rules', r.body.count, JSON.stringify((r.body.results||[]).map(x => ({ledger: x.ledger_name, by: x.created_by, key: x.match_value ?? x.pattern ?? x.payee, at: x.created_at}))).slice(0, 500))
const c = await a.get(`/api/v1/classifications/${ids.Beta_cls[3].id}/`)
console.log('cls3 counterparty', c.body.counterparty, 'method', c.body.method, 'rule', c.body.rule)
console.log('actor', ch.body[0].actor_email, 'note', ch.body[0].note, 'after ledger', JSON.stringify(ch.body[0].after.lines?.map(l=>l.ledger)))
console.log(JSON.stringify(r.body.results.find(x=>x.ledger==='Bank Charges' && /ZEPTO/.test(JSON.stringify(x)))).slice(0,600))
