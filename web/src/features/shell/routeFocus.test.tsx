import { render } from '@testing-library/react'
import { focusPageHeading } from './routeFocus'

function setup(extra = '') {
  const { container } = render(
    <div>
      <button>outside</button>
      <main id="content" tabIndex={-1}>
        <h1>Day Book</h1>
        <a href="#x">tab</a>
        {extra}
      </main>
    </div>,
  )
  return container.querySelector('main') as HTMLElement
}

describe('focusPageHeading', () => {
  it('moves focus from outside the page to the heading', () => {
    const main = setup()
    ;(document.querySelector('button') as HTMLElement).focus()
    expect(focusPageHeading(main)).toBe(true)
    expect(document.activeElement?.tagName).toBe('H1')
  })
  it('leaves focus alone when it is already inside the page', () => {
    const main = setup()
    const link = main.querySelector('a') as HTMLElement
    link.focus()
    focusPageHeading(main)
    expect(document.activeElement).toBe(link)
  })
  it('waits when there is no heading yet, then falls back to the region', () => {
    const { container } = render(<main id="content" tabIndex={-1} />)
    const main = container.querySelector('main') as HTMLElement
    expect(focusPageHeading(main)).toBe(false)
    expect(focusPageHeading(main, { force: true })).toBe(true)
    expect(document.activeElement).toBe(main)
  })
})
