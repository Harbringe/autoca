// The one sentence at the top of a client's overview: how much is waiting and what to do about it, in the
// order the work is done. Pure, so it is tested.

export interface Waiting {
  unresolved: number
  pending: number
  invoices: number
  fixes: number
}

const noun = (n: number, one: string, many: string) => (n === 1 ? one : many)

export function leadSentence(w: Waiting): string {
  const parts: string[] = []
  if (w.unresolved > 0) parts.push(`sort ${w.unresolved}`)
  if (w.pending > 0) parts.push(`record ${w.pending}`)
  if (w.invoices > 0) parts.push(`book ${w.invoices} ${noun(w.invoices, 'invoice', 'invoices')}`)
  if (w.fixes > 0) parts.push(`tie out ${w.fixes} ${noun(w.fixes, 'item', 'items')}`)
  if (parts.length === 0) return 'Nothing is waiting on this client.'
  const total = w.unresolved + w.pending + w.invoices + w.fixes
  return `${total} ${noun(total, 'item needs', 'items need')} you: ${parts.join(', then ')}.`
}
