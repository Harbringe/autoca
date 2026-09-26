// What the server says when it says no.
//
// Every failure has the same envelope -- { code, detail, fields? } -- and the
// detail is written to be read by the person who did the thing: it names the
// row, the figure and the permission. So the app shows the server's sentence
// verbatim and keeps `code` for deciding what to do about it.

export interface ApiErrorBody {
  code: string
  detail: string
  fields?: Record<string, string[] | string>
  verify_at?: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: Record<string, string[]>
  readonly retryAfter: number | null

  constructor(status: number, body: Partial<ApiErrorBody>, retryAfter: number | null = null) {
    super(body.detail || `The server answered ${status}.`)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code || 'error'
    this.retryAfter = retryAfter
    this.fields = {}
    for (const [key, value] of Object.entries(body.fields ?? {})) {
      this.fields[key] = Array.isArray(value) ? value.map(String) : [String(value)]
    }
  }

  /** The first message for one field, for showing beside its input. */
  field(name: string): string | undefined {
    return this.fields[name]?.[0]
  }
}

/** Codes that mean the session itself has changed state, not that a request was wrong. */
export const SESSION_CODES = new Set(['not_authenticated', 'mfa_required', 'mfa_enrolment_required'])

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

/** Short titles for the codes worth naming. Anything else shows the server's own text alone. */
const TITLES: Record<string, string> = {
  balance_chain_broken: 'The statement does not add up',
  no_text_layer: 'This PDF has no readable text',
  unsupported_bank: 'This bank format is not recognised',
  statement_period_missing: 'A month is missing between statements',
  unreadable_file: 'The file could not be read',
  pages_missing: 'Some pages are missing',
  entry_locked: 'The books are locked for this date',
  books_not_ready: 'The books are not ready',
  already_posted: 'Already posted',
  not_approvable: 'Cannot be approved yet',
  in_use: 'In use, so it cannot be removed',
  too_many_attempts: 'Too many attempts',
  gst_rule: 'GST rule',
  gst_file_unreadable: 'The GST file could not be read',
  forbidden: 'Not permitted',
  permission_denied: 'Not permitted',
}

export function errorTitle(error: ApiError): string | undefined {
  return TITLES[error.code]
}

/** A message safe to show for anything thrown, including things that are not ApiErrors. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) return 'Could not reach the server. Check your connection and try again.'
  return error instanceof Error ? error.message : 'Something went wrong.'
}
