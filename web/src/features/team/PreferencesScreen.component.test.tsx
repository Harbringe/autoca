import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PreferencesProvider } from '@/lib/preferences'
import { pageSizeOf, setAllPageSize } from '@/lib/pageSizes'
import { PreferencesScreen } from './PreferencesScreen'

vi.mock('@/lib/title', () => ({ usePageTitle: () => {} }))

const setup = () =>
  render(
    <PreferencesProvider>
      <PreferencesScreen />
    </PreferencesProvider>,
  )

describe('preferences', () => {
  beforeEach(() => {
    localStorage.clear()
    setAllPageSize(null)
  })

  it('has a short menu, with the look first, and changes the theme from a card', async () => {
    const user = userEvent.setup()
    setup()
    const menu = screen.getByRole('navigation', { name: 'Preferences' })
    expect(within(menu).getAllByRole('button').map((b) => b.textContent)).toEqual(['Look', 'Review', 'Rows per page', 'Keyboard'])
    await user.click(screen.getByRole('radio', { name: /Light/ }))
    expect(screen.getByRole('radio', { name: /Light/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: /Dark/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('turns on searching every statement and shows it on the sample', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Review' }))
    const box = screen.getByLabelText('Search every bank statement')
    expect(box).not.toBeChecked()
    await user.click(box)
    expect(box).toBeChecked()
    expect(screen.getByText(/each tagged with where it is from/)).toBeInTheDocument()
    await user.click(box)
  })

  it('sets rows per page for one list and redraws the preview, then resets every list to 10', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Rows per page' }))
    const preview = () => screen.getByRole('region', { name: /Preview of/ })
    expect(within(preview()).getByText(/Review queue/)).toBeInTheDocument()
    // choose Day Book at 25: its preview comes up with 25 rows per page
    const dayBook = screen.getByRole('group', { name: 'Day Book rows per page' })
    fireEvent.click(within(dayBook).getByRole('button', { name: '25' }))
    expect(pageSizeOf('daybook')).toBe(25)
    expect(within(preview()).getByText(/Previewing: Day Book/)).toBeInTheDocument()
    expect(within(preview()).getAllByText('25').length).toBeGreaterThan(0)
    // one number for all lists replaces the single choices
    fireEvent.click(within(screen.getByRole('group', { name: 'All lists rows per page' })).getByRole('button', { name: '50' }))
    expect(pageSizeOf('review')).toBe(50)
    expect(pageSizeOf('daybook')).toBe(50)
    await user.click(screen.getByRole('button', { name: 'Reset all to 10' }))
    expect(pageSizeOf('review')).toBe(10)
    expect(pageSizeOf('daybook')).toBe(10)
  })
})
