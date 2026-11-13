// Reading a pasted list (or a CSV file) of people to invite, one per line.
//
// Each line is an email address, with a name and a role if they are given: "asha@firm.in", "Asha Rao <asha@firm.in>",
// "asha@firm.in, Asha Rao, Staff". A header line ("email, name, role") is skipped. A line that cannot be read is reported with
// its number and the reason, and the lines that can be read still go.

import type { Role } from '@/api/types'

export interface ParsedRow {
  email: string
  full_name?: string
  role?: Role
}

export interface ParseProblem {
  line: number
  text: string
  reason: string
}

export interface ParseResult {
  rows: ParsedRow[]
  problems: ParseProblem[]
}

export const MAX_BULK_ROWS = 50

const ROLE_WORDS: Record<string, Role> = {
  staff: 'STAFF',
  'read only': 'READ_ONLY',
  'read-only': 'READ_ONLY',
  readonly: 'READ_ONLY',
  reader: 'READ_ONLY',
  'senior ca': 'SENIOR_CA',
  senior: 'SENIOR_CA',
  admin: 'FIRM_ADMIN',
  administrator: 'FIRM_ADMIN',
  'firm administrator': 'FIRM_ADMIN',
}

const EMAIL = /^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+$/

const unquote = (s: string) => s.trim().replace(/^"(.*)"$/, '$1').trim()

export function parseInviteLines(text: string): ParseResult {
  const rows: ParsedRow[] = []
  const problems: ParseProblem[] = []
  const seen = new Set<string>()
  const lines = text.split(/\r?\n/)
  let first = true
  lines.forEach((raw, index) => {
    const line = raw.trim()
    if (!line) return
    const isFirst = first
    first = false
    const number = index + 1

    // "Asha Rao <asha@firm.in>"
    const angle = /^(.*?)<([^>]+)>\s*(?:[,;\t]\s*(.*))?$/.exec(line)
    let email = ''
    let name = ''
    let role: Role | undefined
    const leftovers: string[] = []
    if (angle) {
      email = angle[2]!.trim()
      name = unquote(angle[1]!.replace(/[,;]\s*$/, ''))
      if (angle[3]) leftovers.push(...angle[3].split(/[,;\t]/))
    } else {
      for (const field of line.split(/[,;\t]/).map(unquote)) {
        if (!field) continue
        if (!email && EMAIL.test(field)) email = field
        else leftovers.push(field)
      }
    }
    for (const field of leftovers.map(unquote).filter(Boolean)) {
      const asRole = ROLE_WORDS[field.toLowerCase()]
      if (asRole && !role) role = asRole
      else if (!name) name = field
    }

    if (!email) {
      // A first line such as "email, name, role" is a header, not a mistake.
      if (isFirst && /e-?mail/i.test(line) && !line.includes('@')) return
      problems.push({ line: number, text: line, reason: 'No email address on this line.' })
      return
    }
    if (!EMAIL.test(email)) {
      problems.push({ line: number, text: line, reason: `${email} is not an email address.` })
      return
    }
    const key = email.toLowerCase()
    if (seen.has(key)) {
      problems.push({ line: number, text: line, reason: `${email} is listed more than once.` })
      return
    }
    seen.add(key)
    rows.push({ email, ...(name ? { full_name: name } : {}), ...(role ? { role } : {}) })
  })
  return { rows, problems }
}

/** The links of a finished batch as CSV, for people who would rather paste into a mail merge than copy one by one. */
export function linksCsv(results: { email: string; link?: string; role_display?: string }[]): string {
  const cell = (s: string) => `"${s.replace(/"/g, '""')}"`
  return ['email,role,link', ...results.filter((r) => r.link).map((r) => [cell(r.email), cell(r.role_display ?? ''), cell(r.link!)].join(','))].join('\n')
}
