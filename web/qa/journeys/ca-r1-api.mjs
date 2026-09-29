import { signedIn, apiJson } from '../lib/session.mjs'
const role=process.argv[2]; const { page, close } = await signedIn(role)
for (const p of process.argv.slice(3)) { try { console.log(p, JSON.stringify(await apiJson(page,'/'+p.split('/').filter((x,i)=>x||i>0).join('/').replace(/^\/+/,''))).slice(0,+process.env.N||3000)) } catch(e){console.log(p,String(e))} }
await close()
