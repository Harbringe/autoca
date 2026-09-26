import {
  asAt,
  financialYearOf,
  formatDate,
  formatDateLong,
  formatDrCr,
  formatPaise,
  formatPeriod,
  fyLabel,
  fyRange,
  groupIndian,
  parseDate,
  parseRupees,
} from './format'

describe('Indian digit grouping', () => {
  it.each([
    ['0', '0'],
    ['999', '999'],
    ['1000', '1,000'],
    ['100000', '1,00,000'],
    ['1234567', '12,34,567'],
    ['123456789', '12,34,56,789'],
  ])('%s -> %s', (input, expected) => expect(groupIndian(input)).toBe(expected))
})

describe('formatPaise', () => {
  it('always shows two decimals with lakh grouping', () => {
    expect(formatPaise(123456789)).toBe('₹12,34,567.89')
    expect(formatPaise(50)).toBe('₹0.50')
    expect(formatPaise(0)).toBe('₹0.00')
  })
  it('shows a sign for negatives, or none on request', () => {
    expect(formatPaise(-53000)).toBe('-₹530.00')
    expect(formatPaise(-53000, { sign: false, symbol: false })).toBe('530.00')
  })
  it('does not lose paise on a large figure', () => {
    expect(formatPaise(9_999_999_999_99)).toBe('₹9,99,99,99,999.99')
  })
})

describe('formatDrCr', () => {
  it('writes an amount and a side, never a sign', () => {
    expect(formatDrCr(60349057)).toBe('₹6,03,490.57 Dr')
    expect(formatDrCr(-500)).toBe('₹5.00 Cr')
  })
  it('gives zero no side', () => expect(formatDrCr(0)).toBe('₹0.00'))
})

describe('parseRupees', () => {
  it.each([
    ['1,23,456.5', 12345650],
    ['₹ 500', 50000],
    ['500.00', 50000],
    ['0.05', 5],
    ['-12.30', -1230],
  ])('%s -> %s', (input, paise) => expect(parseRupees(input)).toBe(paise))
  it('refuses what it would have to round', () => {
    expect(parseRupees('10.005')).toBeNull()
    expect(parseRupees('abc')).toBeNull()
    expect(parseRupees('')).toBeNull()
  })
})

describe('dates', () => {
  it('writes DD-MM-YYYY without a timezone moving the day', () => {
    expect(formatDate('2026-03-31')).toBe('31-03-2026')
    expect(formatDate(null)).toBe('—')
  })
  it('writes prose dates', () => expect(formatDateLong('2025-04-01')).toBe('1 Apr 2025'))
  it('writes a GST return period', () => expect(formatPeriod('2025-09')).toBe('Sep 2025'))
})

describe('financial year', () => {
  it('runs April to March', () => {
    expect(financialYearOf('2026-03-31')).toBe(2025)
    expect(financialYearOf('2026-04-01')).toBe(2026)
    expect(financialYearOf('2025-12-15')).toBe(2025)
  })
  it('is labelled the way it is written', () => {
    expect(fyLabel(2025)).toBe('2025-26')
    expect(fyLabel(2099)).toBe('2099-00')
    expect(fyRange(2025)).toEqual({ from: '2025-04-01', to: '2026-03-31' })
    expect(asAt(2025)).toBe('as at 31-03-2026')
  })
})

describe('parseDate', () => {
  it.each([
    ['15-04-2025', '2025-04-15'],
    ['1/4/2025', '2025-04-01'],
    ['01.04.2025', '2025-04-01'],
    [' 29-02-2024 ', '2024-02-29'],
  ])('%s -> %s', (input, iso) => expect(parseDate(input)).toBe(iso))
  it('refuses what is not a real date, and never reads it month-first', () => {
    expect(parseDate('31-02-2025')).toBeNull()
    expect(parseDate('29-02-2025')).toBeNull()
    expect(parseDate('13-13-2025')).toBeNull()
    expect(parseDate('2025-04-01')).toBeNull()
    expect(parseDate('')).toBeNull()
  })
})
