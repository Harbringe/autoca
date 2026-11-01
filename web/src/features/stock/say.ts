// What to tell the person when a stock action is refused: the server's own sentence about the field that was wrong when it names one.

import { ApiError } from '@/api/errors'

export const say = (e: unknown): string => {
  if (e instanceof ApiError) return Object.values(e.fields)[0]?.[0] ?? e.message
  return e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.'
}
