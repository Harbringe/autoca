import { describe, expect, it } from 'vitest'
import type { GstGroup, GstReport, GstRow, GstRun } from '@/api/types'
import {
  allowedDecisions,
  currentStep,
  defaultPeriod,
  differenceOf,
  differenceWords,
  fileProblem,
  findRow,
  gstinsOf,
  latestRun,
  mayFinalise,
  monthChoices,
  needsDecision,
  periodName,
  periodProblem,
  signOffGate,
  startsOpen,
  stepsOf,
  taxOf,
  PORTAL_FORMATS,
  REGISTER_FORMATS,
} from './logic'

const inv = (over = {}) => ({
  gstin: '27AABCA1234F1Z5',
  invoice_no: 'INV/1',
  invoice_date: '2026-08-04',
  supplier_name: 'Tata Steel',
  hsn: '7208',
  section: 'B2B' as const,
  taxable_paise: 100000,
  igst_paise: 0,
  cgst_paise: 9000,
  sgst_paise: 9000,
  cess_paise: 0,
  ...over,
})

const row = (over: Partial<GstRow> = {}): GstRow => ({
  id: 'r1',
  itc_status: 'eligible',
  eligible_paise: 18000,
  ineligible_paise: 0,
  cause: '',
  action: '',
  timing: false,
  differences: {},
  book: inv(),
  portal: inv(),
  decision: null,
  ...over,
})

const group = (kind: GstGroup['kind'], rows: GstRow[]): GstGroup => ({ kind, title: kind, count: rows.length, rows })

const report = (over: Partial<GstReport> = {}): GstReport => ({
  id: 'run1',
  registration: { id: 'g1', gstin: '27AABCA1234F1Z5', state_code: '27' },
  period_start: '2026-08-01',
  status: 'draft',
  signed_off_at: null,
  has_register: true,
  has_portal: true,
  summary: { counts: {}, eligible_paise: 0, blocked_paise: 0, ineligible_paise: 0, rcm_liability_paise: 0, unclaimed_in_2b_paise: 0, unresolved: 0 },
  gstr3b: [],
  groups: [group('matched', [row()])],
  actions: [],
  ...over,
})

describe('period', () => {
  const today = new Date(2026, 9, 1) // 1 Oct 2026
  it('accepts a past or current month and refuses the rest with a sentence', () => {
    expect(periodProblem('2026-09', today)).toBeNull()
    expect(periodProblem('2026-10', today)).toBeNull()
    expect(periodProblem('2017-07', today)).toBeNull()
    expect(periodProblem('', today)).toMatch(/Choose/)
    expect(periodProblem('2026-13', today)).toMatch(/Choose/)
    expect(periodProblem('2026-8', today)).toMatch(/Choose/)
    expect(periodProblem('2017-06', today)).toMatch(/July 2017/)
    expect(periodProblem('2026-11', today)).toMatch(/not started/)
  })
  it('lists months newest first and stops where GST began', () => {
    const choices = monthChoices(today, 3)
    expect(choices.map((c) => c.value)).toEqual(['2026-10', '2026-09', '2026-08'])
    expect(choices[0]!.label).toBe('October 2026')
    expect(monthChoices(new Date(2017, 8, 15), 12).map((c) => c.value)).toEqual(['2017-09', '2017-08', '2017-07'])
  })
  it('defaults to the month that just ended, across a year end', () => {
    expect(defaultPeriod(new Date(2026, 9, 1))).toBe('2026-09')
    expect(defaultPeriod(new Date(2026, 0, 10))).toBe('2025-12')
    expect(defaultPeriod(new Date(2017, 7, 1))).toBe('2017-07')
  })
  it('names a month from either shape the server sends', () => {
    expect(periodName('2026-08')).toBe('August 2026')
    expect(periodName('2026-03-01')).toBe('March 2026')
  })
})

describe('files', () => {
  it('checks the extension against what each upload takes', () => {
    expect(fileProblem({ name: 'Purchases.XLSX', size: 10 }, REGISTER_FORMATS)).toBeNull()
    expect(fileProblem({ name: 'p.csv', size: 10 }, REGISTER_FORMATS)).toBeNull()
    expect(fileProblem({ name: 'p.pdf', size: 10 }, REGISTER_FORMATS)).toBe('Upload a file ending in .xlsx, .xlsm or .csv.')
    expect(fileProblem({ name: 'gstr2b.json', size: 10 }, PORTAL_FORMATS)).toBeNull()
    expect(fileProblem({ name: 'gstr2b.csv', size: 10 }, PORTAL_FORMATS)).toBe('Upload a file ending in .json or .xlsx.')
    expect(fileProblem({ name: 'x.xlsx', size: 0 }, PORTAL_FORMATS)).toBe('The file is empty.')
    expect(fileProblem(undefined, PORTAL_FORMATS)).toBe('Choose a file first.')
  })
})

describe('allowedDecisions', () => {
  it('offers accept and claim only where the server takes them', () => {
    expect(allowedDecisions('amount_mismatch')).toEqual(['accept_match', 'claim_itc', 'disallow_itc', 'defer', 'note'])
    expect(allowedDecisions('possible_match')).toEqual(['accept_match', 'claim_itc', 'disallow_itc', 'defer', 'note'])
    expect(allowedDecisions('tax_head_mismatch')).toEqual(['accept_match', 'claim_itc', 'disallow_itc', 'defer', 'note'])
  })
  it('lets a matched, imported or ISD row be disallowed but not accepted', () => {
    for (const kind of ['matched', 'import', 'isd_credit'] as const) {
      expect(allowedDecisions(kind)).toEqual(['disallow_itc', 'defer', 'note'])
    }
  })
  it('leaves a row missing from one side with defer and note only', () => {
    for (const kind of ['missing_in_2b', 'missing_in_books', 'duplicate', 'invalid_gstin', 'rcm', 'wrong_period'] as const) {
      expect(allowedDecisions(kind)).toEqual(['defer', 'note'])
    }
  })
})

describe('sign-off', () => {
  const senior = { permitted: true, role: 'SENIOR_CA', membershipId: 'm1', leadId: 'm1' }
  it('follows the server: administrator, the lead, or any approver while there is no lead', () => {
    expect(mayFinalise(senior)).toBe(true)
    expect(mayFinalise({ ...senior, role: 'FIRM_ADMIN', leadId: 'm9' })).toBe(true)
    expect(mayFinalise({ ...senior, leadId: 'm9' })).toBe(false)
    expect(mayFinalise({ ...senior, leadId: null })).toBe(true)
    expect(mayFinalise({ ...senior, permitted: false })).toBe(false)
    expect(mayFinalise({ ...senior, role: 'FIRM_ADMIN', permitted: false })).toBe(false)
  })
  it('is allowed when matched and nothing is unresolved', () => {
    expect(signOffGate(report(), senior)).toEqual({ ok: true })
  })
  it('says why not, in order of what to fix', () => {
    expect(signOffGate(report({ status: 'signed_off' }), senior)).toMatchObject({ ok: false, reason: expect.stringMatching(/already/) })
    expect(signOffGate(report(), { ...senior, permitted: false })).toMatchObject({ ok: false, reason: expect.stringMatching(/role/) })
    expect(signOffGate(report(), { ...senior, leadId: 'm9' })).toMatchObject({ ok: false, reason: expect.stringMatching(/Senior CA or a firm administrator/) })
    expect(signOffGate(report({ has_portal: false }), senior)).toMatchObject({ ok: false, reason: expect.stringMatching(/Upload/) })
    expect(signOffGate(report({ groups: [] }), senior)).toMatchObject({ ok: false, reason: expect.stringMatching(/Run the match/) })
    const open = report()
    open.summary.unresolved = 2
    expect(signOffGate(open, senior)).toMatchObject({ ok: false, reason: '2 differences have no decision yet.' })
    open.summary.unresolved = 1
    expect(signOffGate(open, senior)).toMatchObject({ ok: false, reason: '1 difference has no decision yet.' })
  })
})

describe('steps', () => {
  it('reads each step from the report', () => {
    const fresh = report({ has_register: false, has_portal: false, groups: [] })
    expect(stepsOf(fresh).map((s) => s.done)).toEqual([false, false, false, false, false])
    expect(currentStep(fresh)).toBe('register')
    expect(currentStep(report({ has_portal: false, groups: [] }))).toBe('portal')
    expect(currentStep(report({ groups: [] }))).toBe('match')
    const undecided = report()
    undecided.summary.unresolved = 3
    expect(currentStep(undecided)).toBe('decide')
    expect(currentStep(report())).toBe('sign_off')
    expect(currentStep(report({ status: 'signed_off' }))).toBeNull()
  })
})

describe('reading a row', () => {
  it('adds the four tax heads as integers', () => {
    expect(taxOf(inv({ igst_paise: 1, cgst_paise: 2, sgst_paise: 3, cess_paise: 4 }))).toBe(10)
    expect(taxOf(null)).toBeNull()
  })
  it('sums the head differences and states the side in words', () => {
    const r = row({ differences: { taxable_paise: 50000, cgst_paise: 4500, sgst_paise: 4500, igst_paise: 0 } })
    expect(differenceOf(r)).toEqual({ taxable: 50000, tax: 9000 })
    expect(differenceOf(row())).toEqual({ taxable: 0, tax: 0 })
    expect(differenceWords(9000)).toBe('Books higher by 90.00')
    expect(differenceWords(-123456)).toBe('Books lower by 1,234.56')
    expect(differenceWords(0)).toBeNull()
  })
  it('needs a decision only for the kinds the server counts, and only while undecided', () => {
    expect(needsDecision('amount_mismatch', row())).toBe(true)
    expect(needsDecision('amount_mismatch', row({ decision: { kind: 'defer', note: '', at: '' } }))).toBe(false)
    expect(needsDecision('missing_in_2b', row())).toBe(false)
    expect(needsDecision('matched', row())).toBe(false)
  })
  it('opens the groups that have work and leaves matched shut', () => {
    expect(startsOpen(group('amount_mismatch', [row()]))).toBe(true)
    expect(startsOpen(group('missing_in_2b', [row()]))).toBe(true)
    expect(startsOpen(group('matched', [row()]))).toBe(false)
    expect(startsOpen(group('amount_mismatch', [row({ decision: { kind: 'claim_itc', note: '', at: '' } })]))).toBe(false)
  })
  it('finds a row and its group by id', () => {
    const r = report({ groups: [group('matched', [row({ id: 'a' })]), group('amount_mismatch', [row({ id: 'b' })])] })
    expect(findRow(r, 'b')?.group.kind).toBe('amount_mismatch')
    expect(findRow(r, 'zzz')).toBeUndefined()
  })
})

describe('the firm landing', () => {
  const run = (id: string, gstin: string, period_start: string, status: GstRun['status']): GstRun => ({ id, registration: gstin, gstin, period_start, status })
  it('picks the latest month, and a draft over a signed run of the same month', () => {
    const runs = [run('1', 'A', '2026-07-01', 'signed_off'), run('2', 'A', '2026-08-01', 'signed_off'), run('3', 'B', '2026-08-01', 'draft')]
    expect(latestRun(runs)?.id).toBe('3')
    expect(latestRun([])).toBeUndefined()
  })
  it('lists each GSTIN once', () => {
    expect(gstinsOf([run('1', 'A', '2026-07-01', 'draft'), run('2', 'B', '2026-07-01', 'draft'), run('3', 'A', '2026-08-01', 'draft')])).toEqual(['A', 'B'])
  })
})
