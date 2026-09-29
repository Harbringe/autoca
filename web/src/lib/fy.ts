// Which financial year a client's screens show.
//
// The year is a fact about the person's attention, not the firm's data, so it is decided in
// order: a year named in the URL (a report link opens that year), then the year this person
// last picked for this client, then the latest year in which the client has statements or
// vouchers, and only for a client with nothing yet, the current financial year.

export interface FyChoice {
  fy: number
  /** True when a person or a link chose this year, as opposed to the default for the client. */
  explicit: boolean
}

/** A financial year taken from an untrusted value (a query string, storage), or undefined. */
export function parseFy(value: unknown): number | undefined {
  const n = typeof value === 'string' && /^\d{4}$/.test(value) ? Number(value) : value
  return typeof n === 'number' && Number.isInteger(n) && n >= 2000 && n <= 2100 ? n : undefined
}

export function resolveFy(opts: { fromUrl?: number; remembered?: number; dataYears: number[]; current: number }): FyChoice {
  if (opts.fromUrl !== undefined) return { fy: opts.fromUrl, explicit: true }
  if (opts.remembered !== undefined) return { fy: opts.remembered, explicit: true }
  if (opts.dataYears.length) return { fy: Math.max(...opts.dataYears), explicit: false }
  return { fy: opts.current, explicit: false }
}
