// Input masks for the identifiers a CA types all day. They only shape what is typed (case,
// length, stray characters); the server's validation is the rule and always wins.

export type Mask = 'pan' | 'gstin'

const ALNUM = /[^A-Za-z0-9]/g

export function applyMask(mask: Mask, value: string): string {
  const clean = value.replace(ALNUM, '').toUpperCase()
  return mask === 'pan' ? clean.slice(0, 10) : clean.slice(0, 15)
}

/** PAN is AAAAA9999A. */
export const PAN_PATTERN = /^[A-Z]{5}\d{4}[A-Z]$/
/** GSTIN is 2 digits of state code, the PAN, an entity number, Z, and a check character. */
export const GSTIN_PATTERN = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/

export function maskProblem(mask: Mask, value: string): string | null {
  if (!value) return null
  if (mask === 'pan') return PAN_PATTERN.test(value) ? null : 'A PAN looks like AAAAA9999A.'
  return GSTIN_PATTERN.test(value) ? null : 'A GSTIN has 15 characters, like 27AABCA1234F1Z5.'
}
