import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { advanceOnEnter } from './enterToAdvance'

function Form({ onSubmit }: { onSubmit: () => void }) {
  return (
    <form
      aria-label="entry"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
      onKeyDown={(e) => advanceOnEnter(e, e.currentTarget)}
    >
      <input aria-label="One" />
      <input aria-label="Two" />
      <textarea aria-label="Notes" />
      <input aria-label="Combo" role="combobox" aria-expanded="true" />
      <input aria-label="Last" />
      <button type="submit">Save</button>
    </form>
  )
}

describe('advanceOnEnter', () => {
  it('moves to the next field on Enter, and saves from the last one', async () => {
    const onSubmit = vi.fn()
    render(<Form onSubmit={onSubmit} />)
    await userEvent.click(screen.getByLabelText('One'))
    await userEvent.keyboard('{Enter}')
    expect(screen.getByLabelText('Two')).toHaveFocus()
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.click(screen.getByLabelText('Last'))
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('leaves a text area and an open pick-list alone', async () => {
    const onSubmit = vi.fn()
    render(<Form onSubmit={onSubmit} />)
    await userEvent.type(screen.getByLabelText('Notes'), 'a{Enter}b')
    expect(screen.getByLabelText('Notes')).toHaveValue('a\nb')
    await userEvent.click(screen.getByLabelText('Combo'))
    await userEvent.keyboard('{Enter}')
    expect(screen.getByLabelText('Combo')).toHaveFocus()
  })
})
