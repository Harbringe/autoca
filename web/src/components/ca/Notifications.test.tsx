import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTO_CLOSE_MS, toast } from '@/lib/toast'
import { Notifications } from './Notifications'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  act(() => toast.dismiss())
  vi.useRealTimers()
})

describe('Notifications', () => {
  it('lets a success go by itself after a few seconds', () => {
    render(<Notifications />)
    act(() => void toast.success('Client details saved'))
    expect(screen.getByText('Client details saved')).toBeInTheDocument()
    act(() => void vi.advanceTimersByTime(AUTO_CLOSE_MS + 50))
    expect(screen.queryByText('Client details saved')).not.toBeInTheDocument()
  })

  it('holds a warning or an error until it is closed, and says so', () => {
    render(<Notifications />)
    act(() => void toast.error('“Cash” has posted entries, so it cannot be deleted.', { description: 'Edit it and untick Active instead.' }))
    act(() => void vi.advanceTimersByTime(AUTO_CLOSE_MS * 5))
    expect(screen.getByRole('alert')).toHaveTextContent('Edit it and untick Active instead.')
    expect(screen.getByText('Stays')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close notification' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stops the clock while the pointer is on a message', () => {
    render(<Notifications />)
    act(() => void toast.success('Saved'))
    const card = screen.getByRole('status', { name: '' })
    fireEvent.mouseEnter(card)
    act(() => void vi.advanceTimersByTime(AUTO_CLOSE_MS * 3))
    expect(screen.getByText('Saved')).toBeInTheDocument()
    fireEvent.mouseLeave(card)
    act(() => void vi.advanceTimersByTime(AUTO_CLOSE_MS + 50))
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
  })

  it('folds more than three into "+N more", and shows them all when asked', () => {
    render(<Notifications />)
    act(() => {
      for (const n of ['A', 'B', 'C', 'D', 'E']) toast.error(`Problem ${n}`)
    })
    expect(screen.getAllByRole('alert')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: '+2 more' }))
    expect(screen.getAllByRole('alert')).toHaveLength(5)
    fireEvent.click(screen.getByRole('button', { name: 'Show fewer' }))
    expect(screen.getAllByRole('alert')).toHaveLength(3)
  })

  it('clears everything with Clear all', () => {
    render(<Notifications />)
    act(() => {
      toast.error('One')
      toast.warning('Two')
    })
    expect(screen.getByText('2 notifications')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('stays inside the window: the stack has a height limit and its cards scroll inside it', () => {
    const { container } = render(<Notifications />)
    act(() => {
      for (let i = 0; i < 12; i++) toast.error(`Problem ${i}`)
    })
    fireEvent.click(screen.getByRole('button', { name: /more/ }))
    const stack = container.firstElementChild as HTMLElement
    expect(stack.className).toContain('max-h-[calc(100svh-2rem)]')
    // the cards sit in their own scrolling box, so the count and the buttons stay in reach
    expect(screen.getAllByRole('alert')[0]!.parentElement!.className).toContain('overflow-y-auto')
    expect(screen.getByRole('button', { name: 'Clear all' })).toBeInTheDocument()
  })

  it('breaks a very long word, and keeps a long description inside its card', () => {
    render(<Notifications />)
    act(() => void toast.error('x'.repeat(300), { description: 'y'.repeat(2000) }))
    const card = screen.getByRole('alert')
    expect(card.innerHTML).toContain('[overflow-wrap:anywhere]')
    expect(card.innerHTML).toContain('max-h-32')
  })

  it('folds again once few are left, so the next crowd does not arrive unfolded', () => {
    render(<Notifications />)
    act(() => {
      for (const n of ['A', 'B', 'C', 'D', 'E']) toast.error(`Problem ${n}`)
    })
    fireEvent.click(screen.getByRole('button', { name: '+2 more' }))
    act(() => void toast.dismiss())
    act(() => {
      for (const n of ['F', 'G', 'H', 'I', 'J']) toast.error(`Later ${n}`)
    })
    expect(screen.getAllByRole('alert')).toHaveLength(3)
  })
})
