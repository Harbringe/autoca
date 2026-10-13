import { afterEach, describe, expect, it } from 'vitest'
import { toast } from './toast'

// The store is module-level, so the tests read it through a tiny subscriber-free snapshot: dismissing all
// between tests keeps them apart.
import { renderHook, act } from '@testing-library/react'
import { useNotes } from './toast'

const notes = () => renderHook(() => useNotes()).result.current

afterEach(() => act(() => toast.dismiss()))

describe('toast store', () => {
  it('puts the newest message first and keeps successes and information on their own clock', () => {
    act(() => {
      toast.success('Saved')
      toast.info('Rule removed', { description: 'Rows already placed stay where they are.' })
    })
    const list = notes()
    expect(list.map((n) => n.title)).toEqual(['Rule removed', 'Saved'])
    expect(list.every((n) => !n.sticky)).toBe(true)
    expect(list[0]?.description).toBe('Rows already placed stay where they are.')
  })

  it('keeps warnings and errors until they are closed', () => {
    act(() => {
      toast.warning('3 of 5 marked as checked')
      toast.error('Could not delete')
    })
    expect(notes().every((n) => n.sticky)).toBe(true)
  })

  it('treats message as information', () => {
    act(() => void toast.message('This invoice is already booked.'))
    expect(notes()[0]?.kind).toBe('info')
  })

  it('shows a repeated message once', () => {
    act(() => {
      toast.error('Could not save')
      toast.error('Could not save')
      toast.error('Could not save')
    })
    expect(notes()).toHaveLength(1)
  })

  it('closes one message, or all of them', () => {
    let id = 0
    act(() => {
      toast.success('One')
      id = toast.success('Two')
      toast.success('Three')
    })
    act(() => toast.dismiss(id))
    expect(notes().map((n) => n.title)).toEqual(['Three', 'One'])
    act(() => toast.dismiss())
    expect(notes()).toEqual([])
  })
})
