import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/errors'
import type { MastersRun, VoucherRun } from '@/api/queries/tallyImport'
import { guessVoucherType, importEverything, type ChosenFile, type ImportDeps } from './importEverything'

const file = (name: string) => new File(['x'], name)
const run = (over: Partial<VoucherRun['counts']> = {}, extra: Partial<VoucherRun> = {}): VoucherRun =>
  ({
    id: 'r1',
    status: 'PREVIEW',
    counts: { vouchers: 30, will_post: 28, skipped: 2, date_from: '2025-04-01', date_to: '2025-04-29', ...over },
    result: null,
    posting: false,
    ...extra,
  }) as unknown as VoucherRun
const masters = (over: Partial<MastersRun['counts']> = {}): MastersRun =>
  ({ id: 'm1', counts: { create: 0, match: 20, conflict: 0, needs_group: 0, skipped: 0, with_opening: 12, bank_conflicts: 0, difference_display: '', ...over } }) as unknown as MastersRun

function deps(over: Partial<ImportDeps> = {}): ImportDeps {
  return {
    stageVouchers: vi.fn().mockResolvedValue(run()),
    isReadJob: ((a: unknown) => (a as { kind?: string }).kind === 'tally.read') as ImportDeps['isReadJob'],
    waitForRead: vi.fn().mockResolvedValue({ status: 'SUCCEEDED', result: { months: 3 } }),
    confirmVouchers: vi.fn().mockResolvedValue(run({}, { status: 'CONFIRMED', result: { posted: 28 } })),
    refreshVouchers: vi.fn().mockResolvedValue(run()),
    postAll: vi.fn().mockResolvedValue({ queued: 3 }),
    stageMasters: vi.fn().mockResolvedValue(masters()),
    confirmMasters: vi.fn().mockResolvedValue(masters()),
    stageBankReports: vi.fn().mockResolvedValue(run({ will_post: 5 })),
    bankAccounts: vi.fn().mockResolvedValue([{ id: 'acct-1', ledger_name: 'Union Bank C.A A/C-342901010036012' }]),
    say: vi.fn(),
    defaultYear: 2026,
    ...over,
  }
}
const vouchers = (name = 'Transactions.json'): ChosenFile => ({ file: file(name), kind: 'vouchers' })

describe('importEverything', () => {
  it('posts a small vouchers file and says how many were posted and how many left out', async () => {
    const d = deps()
    const lines = await importEverything([vouchers()], [], d)
    expect(d.stageVouchers).toHaveBeenCalledTimes(1)
    expect(d.confirmVouchers).toHaveBeenCalledWith('r1')
    expect(lines).toEqual(['Transactions.json: 28 vouchers posted, 2 left out (the reasons are under Imports below).'])
  })

  it('reads a large file into months, then queues every month once, oldest first', async () => {
    const d = deps({ stageVouchers: vi.fn().mockResolvedValue({ kind: 'tally.read', id: 'j1' }) })
    const lines = await importEverything([vouchers('Year.xml')], [], d)
    expect(d.waitForRead).toHaveBeenCalledTimes(1)
    expect(d.postAll).toHaveBeenCalledTimes(1)
    expect(d.confirmVouchers).not.toHaveBeenCalled()
    expect(lines).toEqual(['Year.xml was read into 3 months.', '3 months queued to post, oldest first.'])
  })

  it('reads a firm\'s own voucher type by its name, says so, and posts', async () => {
    const d = deps({ stageVouchers: vi.fn().mockResolvedValue(run({ unknown_types: { 'GST SALE': 42 } })) })
    const lines = await importEverything([vouchers()], [], d)
    expect(d.refreshVouchers).toHaveBeenCalledWith('r1', { 'GST SALE': 'sales' })
    expect(d.confirmVouchers).toHaveBeenCalledTimes(1)
    expect(lines[0]).toBe('Transactions.json: GST SALE was read as Sales.')
  })

  it('leaves a voucher type whose name does not say what it is for the person to settle', async () => {
    const d = deps({ stageVouchers: vi.fn().mockResolvedValue(run({ unknown_types: { 'GST SALE': 42, 'Adjustment Entry': 3 } })) })
    const lines = await importEverything([vouchers()], [], d)
    expect(d.refreshVouchers).not.toHaveBeenCalled()
    expect(d.confirmVouchers).not.toHaveBeenCalled()
    expect(lines[0]).toContain('Adjustment Entry')
    expect(lines[0]).toContain('Say what they count as')
  })

  it('names what a voucher type plainly is, and nothing it cannot tell', () => {
    expect(guessVoucherType('GST SALE')).toBe('sales')
    expect(guessVoucherType('Sales Return')).toBe('credit note')
    expect(guessVoucherType('Purchase Return')).toBe('debit note')
    expect(guessVoucherType('D/Note')).toBe('debit note')
    expect(guessVoucherType('Cash Payment')).toBe('payment')
    expect(guessVoucherType('Adjustment Entry')).toBe('')
    expect(guessVoucherType('Return Inward')).toBe('')
  })

  it('leaves a file where nothing could be posted, with where to see why', async () => {
    const d = deps({ stageVouchers: vi.fn().mockResolvedValue(run({ will_post: 0, skipped: 30 })) })
    const lines = await importEverything([vouchers()], [], d)
    expect(d.confirmVouchers).not.toHaveBeenCalled()
    expect(lines[0]).toContain('none of its 30 vouchers could be posted')
  })

  it('does not force entries the books already hold: it says so and leaves it', async () => {
    const d = deps({ confirmVouchers: vi.fn().mockRejectedValue(new ApiError(409, { code: 'tally_overlap', detail: 'Entries already there.' })) })
    const lines = await importEverything([vouchers()], [], d)
    expect(lines[0]).toContain('already hold entries')
  })

  it('keeps going when one file cannot be read and says which', async () => {
    const stage = vi.fn().mockRejectedValueOnce(new Error('not a vouchers file')).mockResolvedValueOnce(run())
    const d = deps({ stageVouchers: stage })
    const lines = await importEverything([vouchers('a.xml'), vouchers('b.xml')], [], d)
    expect(lines[0]).toBe('a.xml could not be read: not a vouchers file')
    expect(lines[1]).toContain('b.xml: 28 vouchers posted')
  })

  it('brings in opening balances as at the start of the year the vouchers begin in, before posting them', async () => {
    const order: string[] = []
    const d = deps({
      confirmMasters: vi.fn().mockImplementation(async () => (order.push('openings'), masters())),
      confirmVouchers: vi.fn().mockImplementation(async () => (order.push('vouchers'), run({}, { result: { posted: 28 } }))),
    })
    const lines = await importEverything([vouchers(), { file: file('Ledgers.xml'), kind: 'ledgers' }], [], d)
    expect(d.stageMasters).toHaveBeenCalledWith(expect.any(File), 2025)
    expect(order).toEqual(['openings', 'vouchers'])
    expect(lines).toContain('Opening balances from Ledgers.xml were brought in as at 1 April 2025.')
  })

  it('uses the year before April for January to March vouchers', async () => {
    const d = deps({ stageVouchers: vi.fn().mockResolvedValue(run({ date_from: '2026-02-03' })) })
    await importEverything([vouchers(), { file: file('Ledgers.xml'), kind: 'ledgers' }], [], d)
    expect(d.stageMasters).toHaveBeenCalledWith(expect.any(File), 2025)
  })

  it('does not apply opening balances while a line needs a decision, and sends the person to step 1', async () => {
    const d = deps({ stageMasters: vi.fn().mockResolvedValue(masters({ conflict: 2 })) })
    const lines = await importEverything([{ file: file('Ledgers.xml'), kind: 'ledgers' }], [], d)
    expect(d.confirmMasters).not.toHaveBeenCalled()
    expect(lines[0]).toContain('2 ledger lines need your decision')
  })

  it('does not import bank reports alongside vouchers, because the vouchers already carry those entries', async () => {
    const d = deps()
    const lines = await importEverything([vouchers(), { file: file('bank.xml'), kind: 'bank_report' }], [{ file: 'bank.xml', ledger: 'Union Bank C.A A/C-342901010036012' }], d)
    expect(d.stageBankReports).not.toHaveBeenCalled()
    expect(lines.at(-1)).toContain('count them twice')
  })

  it('imports a bank report on its own, matched to the client\'s account by the ledger name', async () => {
    const d = deps({ confirmVouchers: vi.fn().mockResolvedValue(run({}, { result: { posted: 5 } })) })
    const lines = await importEverything([{ file: file('bank.xml'), kind: 'bank_report' }], [{ file: 'bank.xml', ledger: 'union bank c.a a/c-342901010036012' }], d)
    expect(d.stageBankReports).toHaveBeenCalledWith([{ file: expect.any(File), account: 'acct-1' }])
    expect(lines).toEqual(['1 bank report: 5 entries posted.'])
  })

  it('says when a bank report matches none of the client\'s accounts', async () => {
    const d = deps({ bankAccounts: vi.fn().mockResolvedValue([]) })
    const lines = await importEverything([{ file: file('bank.xml'), kind: 'bank_report' }], [{ file: 'bank.xml', ledger: 'Some Bank' }], d)
    expect(d.stageBankReports).not.toHaveBeenCalled()
    expect(lines[0]).toContain('no bank account of the client matches')
  })
})
