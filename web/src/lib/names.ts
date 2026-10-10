// Names written one way, so lists and forms look the same. Mirrors core/names.py: a word that already mixes cases
// (McDonald, iPhone) is left as typed; initialisms (S.B.H) and a few firm-type words stay in capitals.

const KEEP_UPPER = new Set(['LLP', 'HUF', 'OPC', 'GST', 'TDS', 'MSME', 'LLC', 'HP', 'BP', 'UP', 'MP', 'AP', 'II', 'III', 'IV', 'ATM', 'SBI', 'HDFC', 'ICICI', 'LIC', 'NTPC', 'ONGC', 'TCS', 'IBM'])
const SMALL = new Set(['and', 'of', 'the', 'for', 'in', 'at', 'on', 'to'])
const INITIALS = /^(?:[A-Za-z]\.)+[A-Za-z]?\.?$/

function casePart(part: string): string {
  if (part.length <= 1) return part.toUpperCase()
  return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
}

function word(w: string, first: boolean): string {
  if (w === '&') return w
  const stripped = w.replace(/^[.,()&]+|[.,()&]+$/g, '')
  if (INITIALS.test(w)) return w.toUpperCase()
  if (/[a-z]/.test(stripped) && /[A-Z]/.test(stripped.slice(1))) return w
  if (KEEP_UPPER.has(stripped.toUpperCase())) return w.toUpperCase()
  if (!first && SMALL.has(stripped.toLowerCase())) return w.toLowerCase()
  if (/\d/.test(w)) return w === w.toUpperCase() ? w.toUpperCase() : w
  return w.replace(/[A-Za-z]+/g, (m) => casePart(m))
}

export function normaliseName(text: string | null | undefined): string {
  const words = String(text ?? '').split(/\s+/).filter(Boolean)
  return words.map((w, i) => word(w, i === 0)).join(' ')
}
