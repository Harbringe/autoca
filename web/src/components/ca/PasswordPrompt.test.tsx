import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { isLockedCode, PasswordForm } from './PasswordPrompt'

describe('asking for the password of a locked PDF', () => {
  it('knows the two answers that mean the file is locked', () => {
    expect(isLockedCode('password_required')).toBe(true)
    expect(isLockedCode('password_incorrect')).toBe(true)
    expect(isLockedCode('unreadable_file')).toBe(false)
    expect(isLockedCode(undefined)).toBe(false)
  })

  it('sends what was typed once and empties the field straight away', async () => {
    const onSubmit = vi.fn()
    render(<PasswordForm fileName="stmt.pdf" wrong={false} onSubmit={onSubmit} onCancel={() => {}} />)
    const field = screen.getByLabelText('Password')
    expect(field).toHaveAttribute('type', 'password')
    expect(field).toHaveAttribute('autocomplete', 'off')
    await userEvent.type(field, 'Sup3r-Secret')
    await userEvent.click(screen.getByRole('button', { name: 'Open and read' }))
    expect(onSubmit).toHaveBeenCalledWith('Sup3r-Secret')
    expect(field).toHaveValue('')
  })

  it('does not send an empty password', async () => {
    const onSubmit = vi.fn()
    render(<PasswordForm fileName="stmt.pdf" wrong={false} onSubmit={onSubmit} onCancel={() => {}} />)
    expect(screen.getByRole('button', { name: 'Open and read' })).toBeDisabled()
  })

  it('says the last password did not open it, in its own words, not "damaged"', () => {
    render(<PasswordForm fileName="stmt.pdf" wrong onSubmit={() => {}} onCancel={() => {}} />)
    expect(screen.getByText(/That password did not open the file/)).toBeInTheDocument()
    expect(screen.queryByText(/damaged/i)).not.toBeInTheDocument()
  })

  it('says it is used once and the file stays locked', () => {
    render(<PasswordForm fileName="stmt.pdf" wrong={false} onSubmit={() => {}} onCancel={() => {}} />)
    expect(screen.getByText(/It is used once, to read this file. It is not saved/)).toBeInTheDocument()
  })
})
