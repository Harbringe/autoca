import { describe, expect, it } from 'vitest'
import { Route } from '@/routes/_app/clients/$clientId/reports'
import { REPORT_TABS } from './tabs'

describe('the Reports route', () => {
  it('accepts every tab the tab row shows', () => {
    const validate = Route.options.validateSearch as (s: Record<string, unknown>) => { report: string }
    for (const { tab } of REPORT_TABS) expect(validate({ report: tab }).report).toBe(tab)
  })

  it('falls back to the Trial Balance for a tab it does not know', () => {
    const validate = Route.options.validateSearch as (s: Record<string, unknown>) => { report: string }
    expect(validate({ report: 'nope' }).report).toBe('tb')
  })
})
