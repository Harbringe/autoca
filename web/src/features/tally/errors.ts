import { isApiError } from '@/api/errors'

/** The sentence to show for a failed Tally request: the server's own, and for a rejected field, that field's message rather than "Some fields are invalid". */
export function messageOf(error: unknown): string {
  if (isApiError(error) && error.code === 'invalid') {
    const first = Object.values(error.fields).flat()[0]
    if (first) return first
  }
  return error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.'
}
