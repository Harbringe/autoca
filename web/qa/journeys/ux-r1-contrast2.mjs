import { signedIn, WEB } from '../lib/session.mjs'
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
const paths = ['/clients', `/clients/${CID}`, `/clients/${CID}/review`, `/clients/${CID}/daybook`, `/clients/${CID}/reports`, `/clients/${CID}/books`, `/clients/${CID}/masters`, `/clients/${CID}/statements`]
for (const dark of [false, true]) {
  const { page, close } = await signedIn('admin', { dark })
  const seen = new Map()
  for (const p of paths) {
    await page.goto(WEB + p); await page.waitForTimeout(1600)
    if (p.includes('reports')) { await page.getByText('Show FY 2025-26').click().catch(()=>{}); await page.waitForTimeout(1200) }
    const res = await page.evaluate(() => {
      const parse = (s) => { const m = s.match(/rgba?\(([^)]+)\)|color\(srgb ([^)]+)\)/); if(!m) return null; if (m[2]) { const v=m[2].split(/[ /]+/).map(Number); return [v[0]*255,v[1]*255,v[2]*255, v[3]??1] } const v=m[1].split(',').map(Number); return [v[0],v[1],v[2],v[3]??1] }
      const canvas = document.createElement('canvas').getContext('2d')
      const norm = (c) => { canvas.fillStyle = '#000'; canvas.fillStyle = c; const h = canvas.fillStyle; if (h.startsWith('#')) return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16),1]; return parse(h) }
      const lum = ([r,g,b]) => { const a=[r,g,b].map(v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4}); return .2126*a[0]+.7152*a[1]+.0722*a[2] }
      const blend = (f,b) => f[3]>=1?f:[f[0]*f[3]+b[0]*(1-f[3]),f[1]*f[3]+b[1]*(1-f[3]),f[2]*f[3]+b[2]*(1-f[3]),1]
      const bgOf = (el) => { const chain=[]; for (let e=el;e;e=e.parentElement){ const c=norm(getComputedStyle(e).backgroundColor); if(c&&c[3]>0){chain.push(c); if(c[3]>=1)break} } let bg=[255,255,255,1]; for(const c of chain.reverse()) bg=blend(c,bg); return bg }
      const out=[]
      for (const el of document.querySelectorAll('body *')) {
        if (![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())) continue
        const r=el.getBoundingClientRect(); if(!r.width||!r.height) continue
        const cs=getComputedStyle(el); if(cs.visibility==='hidden') continue
        let op=1; for(let e=el;e;e=e.parentElement) op*=parseFloat(getComputedStyle(e).opacity)
        const fg0=norm(cs.color); if(!fg0) continue
        const bg=bgOf(el); let fg=blend([fg0[0],fg0[1],fg0[2],fg0[3]*op],bg)
        const L1=lum(fg),L2=lum(bg); const ratio=(Math.max(L1,L2)+.05)/(Math.min(L1,L2)+.05)
        const size=parseFloat(cs.fontSize), bold=parseInt(cs.fontWeight)>=700
        const need=(size>=24||(size>=18.66&&bold))?3:4.5
        if(ratio<need) out.push({t:el.textContent.trim().slice(0,28),ratio:+ratio.toFixed(2),need,size,fg:cs.color.slice(0,30)})
      }
      return out
    })
    for (const r of res) { const k=r.t+'|'+r.ratio; if(!seen.has(k)) seen.set(k,{...r,p}) }
  }
  console.log(dark?'=== DARK':'=== LIGHT', seen.size)
  for (const r of [...seen.values()].sort((a,b)=>a.ratio-b.ratio).slice(0,25)) console.log(r.ratio, r.need, r.size+'px', JSON.stringify(r.t), r.p.replace(CID,':id'))
  await close()
}
