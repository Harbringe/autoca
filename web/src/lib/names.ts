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

const FORM_WORDS = new Set(['pvt', 'private', 'ltd', 'limited', 'llp', 'co', 'company', 'corp', 'corporation', 'inc', 'the', 'and', 'm', 's', 'ms', 'mrs', 'mr', 'shri', 'shree', 'sri'])

/** The words that say which business this is: lower case, no punctuation, none of the "Pvt Ltd" kind. */
function tokens(text: string): Set<string> {
  const words = String(text ?? '').toLowerCase().match(/[a-z0-9]+/g) ?? []
  return new Set(words.filter((w) => !FORM_WORDS.has(w) && (w.length > 1 || /\d/.test(w))))
}

/** Whether two spellings name the same business: one's identifying words all appear in the other, and there are at least two. */
export function sameBusiness(a: string, b: string): boolean {
  const left = tokens(a)
  const right = tokens(b)
  if (left.size < 2 || right.size < 2) return false
  const [small, large] = left.size <= right.size ? [left, right] : [right, left]
  return [...small].every((w) => large.has(w))
}
