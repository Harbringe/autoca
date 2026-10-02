import { describe, expect, it } from 'vitest'
import type { FirmMetrics, MetricsClient, MetricsTurnaround } from '@/api/types'
import { attentionClients, daysText, estimateNote, minutesText, NOT_ENOUGH_DATA, percentText, turnaroundByName } from './metrics'

describe('percentText', () => {
  it('writes a ratio as a whole percent', () => {
    expect(percentText(0.857)).toBe('86%')
    expect(percentText(1)).toBe('100%')
    expect(percentText(0)).toBe('0%')
  })
  it('is null, never 0% or NaN, when there is nothing to say', () => {
    expect(percentText(null)).toBeNull()
    expect(percentText(undefined)).toBeNull()
    expect(percentText(Number.NaN)).toBeNull()
    expect(percentText(Number.POSITIVE_INFINITY)).toBeNull()
  })
  it('stays inside 0 to 100', () => {
    expect(percentText(1.2)).toBe('100%')
    expect(percentText(-0.1)).toBe('0%')
  })
})

describe('minutesText and daysText', () => {
  it('splits hours from minutes', () => {
    expect(minutesText(45)).toBe('45 min')
    expect(minutesText(60)).toBe('1 h')
    expect(minutesText(130)).toBe('2 h 10 min')
    expect(minutesText(0)).toBe('0 min')
  })
  it('says days to one decimal and leaves null as words', () => {
    expect(daysText(2)).toBe('2 days')
    expect(daysText(1.04)).toBe('1 day')
    expect(daysText(0.45)).toBe('0.5 days')
    expect(daysText(null)).toBe(NOT_ENOUGH_DATA)
    expect(daysText(Number.NaN)).toBe(NOT_ENOUGH_DATA)
  })
  it('labels the estimate as an assumption', () => {
    expect(estimateNote(2)).toBe('Estimate: 2 min per row assumed')
  })
})

const client = (name: string, reasons: number): MetricsClient =>
  ({ id: name, name, needs_attention: Array.from({ length: reasons }, () => ({ code: 'suspense_balance', message: 'Suspense holds a balance.' })) }) as unknown as MetricsClient
const person = (name: string): MetricsTurnaround => ({ member: { id: name, name }, statements_completed: 0, median_days_upload_to_posted: null, books_signed_off: 0, median_days_request_to_sign_off: null })

describe('lists', () => {
  it('lists only clients with a reason, alphabetically', () => {
    const m = { clients: [client('Zed', 1), client('Quiet', 0), client('Alpha', 2)] } as Pick<FirmMetrics, 'clients'>
    expect(attentionClients(m).map((c) => c.name)).toEqual(['Alpha', 'Zed'])
  })
  it('lists people alphabetically and leaves the input alone', () => {
    const m = { turnaround: [person('Sanjay'), person('Asha'), person('Meera')] }
    expect(turnaroundByName(m).map((t) => t.member.name)).toEqual(['Asha', 'Meera', 'Sanjay'])
    expect(m.turnaround[0]!.member.name).toBe('Sanjay')
  })
})
