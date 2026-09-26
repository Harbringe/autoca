import { fireEvent, render, screen } from '@testing-library/react'
import { HotkeyProvider, useHotkey } from './hotkeys'

function Harness({ onEnter }: { onEnter: () => void }) {
  useHotkey('enter', 'Place', onEnter)
  return (
    <>
      <input aria-label="ledger" />
      <input type="checkbox" aria-label="remember" />
      <button type="button">Post</button>
      <div role="dialog">
        <button type="button">Confirm</button>
        <input type="checkbox" aria-label="in dialog" />
      </div>
    </>
  )
}

function setup() {
  const onEnter = vi.fn()
  render(
    <HotkeyProvider>
      <Harness onEnter={onEnter} />
    </HotkeyProvider>,
  )
  return onEnter
}

describe('plain-key shortcuts', () => {
  it('still work while a checkbox has focus, since there is nothing to type into', () => {
    const onEnter = setup()
    fireEvent.keyDown(screen.getByLabelText('remember'), { key: 'Enter' })
    expect(onEnter).toHaveBeenCalledOnce()
  })
  it('stay out of the way while typing in a text box', () => {
    const onEnter = setup()
    fireEvent.keyDown(screen.getByLabelText('ledger'), { key: 'Enter' })
    expect(onEnter).not.toHaveBeenCalled()
  })
  it('do not act on top of a focused button, which Enter already presses', () => {
    const onEnter = setup()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Post' }), { key: 'Enter' })
    expect(onEnter).not.toHaveBeenCalled()
  })
  it('never reach the screen behind an open dialog', () => {
    const onEnter = setup()
    fireEvent.keyDown(screen.getByLabelText('in dialog'), { key: 'Enter' })
    expect(onEnter).not.toHaveBeenCalled()
  })
})
