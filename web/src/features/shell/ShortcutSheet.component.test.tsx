import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HotkeyProvider, useHotkey } from '@/lib/hotkeys'
import { ShortcutSheet } from './ShortcutSheet'

function Keys({ onJ }: { onJ: () => void }) {
  useHotkey('j', 'Next row', onJ, 'Review')
  useHotkey('p', 'Post this row', () => {}, 'Review')
  useHotkey('g l', 'This client: Ledgers', () => {}, 'Go to')
  useHotkey('ctrl+k', 'Search clients', () => {})
  return <ShortcutSheet open onOpenChange={() => {}} />
}
const setup = (onJ = vi.fn()) => render(<HotkeyProvider><Keys onJ={onJ} /></HotkeyProvider>)

describe('the keyboard guide', () => {
  it('lists the headings with counts, the screen first and marked here', async () => {
    setup()
    const nav = await screen.findByRole('navigation', { name: 'Shortcut headings' })
    const names = within(nav).getAllByRole('button').map((b) => b.textContent)
    expect(names).toEqual(['Reviewhere2', 'Go to1', 'Everywhere1'])
    expect(screen.getByText('Post this row')).toBeInTheDocument()
  })

  it('searches every heading at once and says how many match', async () => {
    const user = userEvent.setup()
    setup()
    await user.type(await screen.findByRole('searchbox', { name: 'Find a shortcut' }), 'ledger')
    expect(screen.getByText('This client: Ledgers')).toBeInTheDocument()
    expect(screen.queryByText('Post this row')).toBeNull()
    expect(screen.getByText('1 shortcut matches')).toBeInTheDocument()
  })

  it('lights the row of a pressed key without running what the key does', async () => {
    const onJ = vi.fn()
    setup(onJ)
    await screen.findByText('Next row')
    act(() => void fireEvent.keyDown(screen.getByRole('button', { name: /Review/ }), { key: 'j' }))
    expect(screen.getByText('Next row').closest('li')).toHaveAttribute('data-lit')
    expect(onJ).not.toHaveBeenCalled()
  })
})
