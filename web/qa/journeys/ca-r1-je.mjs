import { signedIn, apiJson } from '../lib/session.mjs'
const [role,cid]=process.argv.slice(2); const { page, close } = await signedIn(role)
const j = await apiJson(page,`/api/v1/journal-entries/?client=${cid}&live=true&page_size=200`)
console.log(j.count, Object.keys(j.results[0]).join(','))
for (const e of j.results) console.log(e.entry_date, e.voucher_type, e.entry_no, (e.narration||'').slice(0,90), JSON.stringify((e.lines||[]).map(l=>[l.ledger_name||l.ledger,l.debit_paise,l.credit_paise])))
await close()
