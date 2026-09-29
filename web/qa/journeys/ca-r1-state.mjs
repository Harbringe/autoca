import { signedIn, apiJson } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
for (const [n,id] of [['Ashok','73d99780-eca9-48e7-8ab2-a8e1cee1271f'],['Bindal','8b70e7ab-e10d-40ac-818c-9cdf9112db03']]) {
  const b = `/api/v1/clients/${id}`
  for (const p of ['statements/','review-queue/summary/','books/','reports/trial-balance/','journal-entries/']) {
    try { const j = await apiJson(page, `${b}/${p}`); console.log(n,p,JSON.stringify(j).slice(0,1500)) } catch(e){console.log(n,p,String(e))}
  }
}
await close()
