import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './dialog'

// A dialog opened from state has no Trigger, so Radix has nowhere to return focus (UX-008).
function Opener() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open it</button>
      <main id="content" tabIndex={-1} />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>Title</DialogTitle>
          <DialogDescription>Body</DialogDescription>
          <button>Inside</button>
        </DialogContent>
      </Dialog>
    </>
  )
}

describe('DialogContent focus', () => {
  it('returns focus to the button that opened it when closed with Escape', async () => {
    const user = userEvent.setup()
    render(<Opener />)
    const button = screen.getByRole('button', { name: 'Open it' })
    await user.click(button)
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(button).toHaveFocus()
  })
  it('lands on the main region when the opener has gone', async () => {
    const user = userEvent.setup()
    function Gone() {
      const [open, setOpen] = useState(false)
      const [shown, setShown] = useState(true)
      return (
        <>
          {shown && (
            <button
              onClick={() => {
                setOpen(true)
              }}
            >
              Open it
            </button>
          )}
          <main id="content" tabIndex={-1} />
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent>
              <DialogTitle>Title</DialogTitle>
              <DialogDescription>Body</DialogDescription>
              <button onClick={() => setShown(false)}>Remove opener</button>
            </DialogContent>
          </Dialog>
        </>
      )
    }
    render(<Gone />)
    await user.click(screen.getByRole('button', { name: 'Open it' }))
    await user.click(await screen.findByRole('button', { name: 'Remove opener' }))
    await user.keyboard('{Escape}')
    expect(document.getElementById('content')).toHaveFocus()
  })
})
