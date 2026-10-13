import { afterEach, describe, expect, it, vi } from 'vitest'
import { watchScrolling } from './scrollbars'

describe('scrollbar visibility', () => {
  let stop = () => {}
  afterEach(() => {
    stop()
    document.body.replaceChildren()
    vi.useRealTimers()
  })

  it('marks what scrolled for a moment, then clears it', () => {
    vi.useFakeTimers()
    stop = watchScrolling()
    const box = document.createElement('div')
    document.body.appendChild(box)
    box.dispatchEvent(new Event('scroll'))
    expect(box).toHaveAttribute('data-scrolling')
    vi.advanceTimersByTime(1000)
    expect(box).not.toHaveAttribute('data-scrolling')
  })

  it('marks the scroller under the pointer, and moves the mark when the pointer moves to another', () => {
    stop = watchScrolling()
    const make = () => {
      const el = document.createElement('div')
      el.style.overflowY = 'auto'
      Object.defineProperty(el, 'scrollHeight', { value: 500 })
      Object.defineProperty(el, 'clientHeight', { value: 100 })
      document.body.appendChild(el)
      return el
    }
    const a = make()
    const b = make()
    a.dispatchEvent(new Event('pointermove', { bubbles: true }))
    expect(a).toHaveAttribute('data-scroll-hover')
    b.dispatchEvent(new Event('pointermove', { bubbles: true }))
    expect(a).not.toHaveAttribute('data-scroll-hover')
    expect(b).toHaveAttribute('data-scroll-hover')
  })
})
