import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Confirm } from './Confirm'

function renderConfirm(onConfirm: () => Promise<unknown>, onOpenChange = vi.fn()) {
  render(
    <Confirm open onOpenChange={onOpenChange} title="Unpost this entry?" confirmLabel="Unpost" busyLabel="Unposting 2 of 5…" onConfirm={onConfirm}>
      <p>It leaves the books.</p>
    </Confirm>,
  )
  return onOpenChange
}

describe('Confirm while the server works', () => {
  it('keeps the dialog open, spins the button and says what it is doing', async () => {
    let finish: () => void = () => {}
    const onOpenChange = renderConfirm(() => new Promise<void>((resolve) => (finish = resolve)))
    await userEvent.click(screen.getByRole('button', { name: 'Unpost' }))
    const working = await screen.findByRole('button', { name: /Unposting 2 of 5/ })
    expect(working).toHaveAttribute('aria-busy', 'true')
    expect(working).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(onOpenChange).not.toHaveBeenCalled()
    finish()
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('stays open with the reason when the server refuses', async () => {
    const onOpenChange = renderConfirm(() => Promise.reject(new Error('The books are signed off.')))
    await userEvent.click(screen.getByRole('button', { name: 'Unpost' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The books are signed off.')
    expect(onOpenChange).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Unpost' })).not.toHaveAttribute('aria-busy')
  })
})
