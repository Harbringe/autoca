import { signedIn, WEB } from '../lib/session.mjs'

function relLum([r,g,b]) {
  const a = [r,g,b].map(v => { v/=255; return v<=0.03928? v/12.92: Math.pow((v+0.055)/1.055,2.4) })
  return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2]
}
function parseColor(s) {
  const m = s.match(/rgba?\(([^)]+)\)/)
  if (!m) return null
  return m[1].split(',').map(Number)
}
function contrast(c1, c2) {
  const l1 = relLum(c1), l2 = relLum(c2)
  const [hi,lo] = l1>l2? [l1,l2]:[l2,l1]
  return (hi+0.05)/(lo+0.05)
}

async function check(dark) {
  const { page, close } = await signedIn('admin', { width: 1440, height: 900, dark })
  const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
  await page.goto(`${WEB}/clients/${CID}/review`)
  await page.waitForTimeout(1500)
  const targets = await page.evaluate(() => {
    const texts = Array.from(document.querySelectorAll('body *')).filter(e => e.children.length===0 && e.textContent.trim().length>1)
    const out = []
    const seen = new Set()
    for (const el of texts) {
      const cs = getComputedStyle(el)
      const key = cs.color+'|'+cs.fontSize
      if (seen.has(key)) continue
      seen.add(key)
      // find bg by walking up
      let bgEl = el, bg = 'rgba(0,0,0,0)'
      while (bgEl) {
        const c = getComputedStyle(bgEl).backgroundColor
        if (c && c !== 'rgba(0, 0, 0, 0)') { bg = c; break }
        bgEl = bgEl.parentElement
      }
      out.push({ text: el.textContent.trim().slice(0,30), color: cs.color, bg, fontSize: cs.fontSize, fontWeight: cs.fontWeight })
    }
    return out
  })
  console.log(dark ? '=== DARK ===' : '=== LIGHT ===')
  for (const t of targets) {
    const c1 = parseColor(t.color), c2 = parseColor(t.bg)
    if (!c1 || !c2) continue
    const ratio = contrast(c1, c2)
    if (ratio < 4.5) console.log(`LOW ${ratio.toFixed(2)}:1  "${t.text}"  color=${t.color} bg=${t.bg} size=${t.fontSize} weight=${t.fontWeight}`)
  }
  await close()
}
await check(false)
await check(true)
