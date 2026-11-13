import { describe, expect, it } from 'vitest'
import { linksCsv, parseInviteLines } from './bulkInvite'

describe('parseInviteLines', () => {
  it('reads one address per line, with an optional name and role in any of the usual shapes', () => {
    const { rows, problems } = parseInviteLines(
      ['a@firm.test', 'Bea Rao <b@firm.test>', 'c@firm.test, Cy Das, Staff', 'd@firm.test;Dee Eng;read only', '"e@firm.test","Eve Fox","Senior CA"'].join('\n'),
    )
    expect(problems).toEqual([])
    expect(rows).toEqual([
      { email: 'a@firm.test' },
      { email: 'b@firm.test', full_name: 'Bea Rao' },
      { email: 'c@firm.test', full_name: 'Cy Das', role: 'STAFF' },
      { email: 'd@firm.test', full_name: 'Dee Eng', role: 'READ_ONLY' },
      { email: 'e@firm.test', full_name: 'Eve Fox', role: 'SENIOR_CA' },
    ])
  })

  it('skips blank lines and a header line without calling them mistakes', () => {
    const { rows, problems } = parseInviteLines('email, name, role\n\n  a@firm.test  \r\n\r\nb@firm.test\n')
    expect(problems).toEqual([])
    expect(rows.map((r) => r.email)).toEqual(['a@firm.test', 'b@firm.test'])
  })

  it('reports an unreadable line with its number and why, and still reads the others', () => {
    const { rows, problems } = parseInviteLines('a@firm.test\nnot an address\nb@firm\nc@firm.test')
    expect(rows.map((r) => r.email)).toEqual(['a@firm.test', 'c@firm.test'])
    expect(problems).toEqual([
      { line: 2, text: 'not an address', reason: 'No email address on this line.' },
      { line: 3, text: 'b@firm', reason: 'No email address on this line.' },
    ])
  })

  it('refuses an address listed twice, whatever its capitals', () => {
    const { rows, problems } = parseInviteLines('a@firm.test\nA@Firm.test, Again')
    expect(rows).toHaveLength(1)
    expect(problems[0]).toMatchObject({ line: 2, reason: 'A@Firm.test is listed more than once.' })
  })

  it('treats a name with a comma inside quotes as one name and ignores an unknown role word as part of the name only once', () => {
    const { rows } = parseInviteLines('a@firm.test, Rao, Asha, Staff')
    expect(rows[0]).toMatchObject({ email: 'a@firm.test', full_name: 'Rao', role: 'STAFF' })
  })

  it('returns nothing for empty input', () => {
    expect(parseInviteLines('')).toEqual({ rows: [], problems: [] })
    expect(parseInviteLines('  \n \n')).toEqual({ rows: [], problems: [] })
  })
})

describe('linksCsv', () => {
  it('lists the links that were made and leaves out the rows that failed, quoting what needs it', () => {
    const csv = linksCsv([
      { email: 'a@firm.test', link: 'https://x.test/invite/1', role_display: 'Staff' },
      { email: 'b@firm.test' },
      { email: 'c@firm.test', link: 'https://x.test/invite/2?a="b"', role_display: 'Read only' },
    ])
    expect(csv.split('\n')).toEqual([
      'email,role,link',
      '"a@firm.test","Staff","https://x.test/invite/1"',
      '"c@firm.test","Read only","https://x.test/invite/2?a=""b"""',
    ])
  })
})
