import { presetRange, rangeProblem } from './period'

describe('presetRange', () => {
  const today = new Date(2026, 8, 29) // 29 Sep 2026
  it('this month runs from the 1st to today', () => expect(presetRange('month', today)).toEqual({ from: '2026-09-01', to: '2026-09-29' }))
  it('last month is the whole month', () => expect(presetRange('last', today)).toEqual({ from: '2026-08-01', to: '2026-08-31' }))
  it('last month in January reaches back to December', () =>
    expect(presetRange('last', new Date(2027, 0, 10))).toEqual({ from: '2026-12-01', to: '2026-12-31' }))
  it('this financial year starts on the 1st of April', () => expect(presetRange('fy', today)).toEqual({ from: '2026-04-01', to: '2026-09-29' }))
  it('in February the financial year began the April before', () =>
    expect(presetRange('fy', new Date(2027, 1, 3))).toEqual({ from: '2026-04-01', to: '2027-02-03' }))
})

describe('rangeProblem', () => {
  it('accepts an ordinary range', () => expect(rangeProblem({ from: '2026-04-01', to: '2026-09-29' })).toBeNull())
  it('refuses a reversed range', () => expect(rangeProblem({ from: '2026-05-01', to: '2026-04-01' })).toMatch(/before/))
  it('refuses more than a year', () => expect(rangeProblem({ from: '2025-01-01', to: '2026-06-01' })).toMatch(/year/))
  it('asks for both dates', () => expect(rangeProblem(null)).toMatch(/DD-MM-YYYY/))
})
