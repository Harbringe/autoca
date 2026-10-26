import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TrialStrip } from './Shell'

const session = vi.hoisted(() => ({ me: null as unknown }))
vi.mock('@/session/session', () => ({ useSession: () => ({ me: session.me, can: () => true }) }))

const show = (trial: unknown) => {
  session.me = { trial }
  render(<TrialStrip />)
}

describe('the trial notice', () => {
  it('says nothing when there is no trial to mention', () => {
    show(null)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('counts the days left and says to ask the platform owner', () => {
    show({ ends_at: '2026-12-20T18:29:59Z', days_left: 9 })
    expect(screen.getByRole('status')).toHaveTextContent(/Your trial ends in 9 days/)
    expect(screen.getByRole('status')).toHaveTextContent('Contact the platform owner to carry on.')
  })

  it('says tomorrow and today in words', () => {
    show({ ends_at: '2026-12-20T18:29:59Z', days_left: 1 })
    expect(screen.getByRole('status')).toHaveTextContent('Your trial ends tomorrow.')
  })

  it('says it has ended once the date has passed', () => {
    show({ ends_at: '2026-12-01T18:29:59Z', days_left: -4 })
    expect(screen.getByRole('status')).toHaveTextContent(/Your trial ended on/)
  })
})
