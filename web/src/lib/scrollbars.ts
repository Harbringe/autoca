// Scrollbars that keep out of the way: the track is never drawn, and the thumb shows only while something is scrolling or the pointer is
// over the thing that scrolls (the rules are in styles.css and key off two attributes set here). CSS alone cannot do both: it does not
// know "was just scrolled", and browsers do not redraw a scrollbar part when :hover changes. Two listeners on the document, no work per element.

const SHOW_MS = 900
const timers = new WeakMap<Element, number>()

/** The nearest thing around `from` that has a scrollbar to show, if any. */
function scroller(from: EventTarget | null): Element | null {
  let el = from instanceof Element ? from : null
  while (el && el !== document.documentElement) {
    const { overflowY, overflowX } = getComputedStyle(el)
    const y = /auto|scroll/.test(overflowY) && el.scrollHeight > el.clientHeight + 1
    const x = /auto|scroll/.test(overflowX) && el.scrollWidth > el.clientWidth + 1
    if (y || x) return el
    el = el.parentElement
  }
  return null
}

export function watchScrolling(doc: Document = document) {
  const root = doc.documentElement
  const onScroll = (e: Event) => {
    const target = e.target instanceof Element ? e.target : root
    target.setAttribute('data-scrolling', '')
    window.clearTimeout(timers.get(target))
    timers.set(
      target,
      window.setTimeout(() => target.removeAttribute('data-scrolling'), SHOW_MS),
    )
  }
  let hovered: Element | null = null
  const onMove = (e: PointerEvent) => {
    const next = scroller(e.target)
    if (next === hovered) return
    hovered?.removeAttribute('data-scroll-hover')
    next?.setAttribute('data-scroll-hover', '')
    hovered = next
  }
  // Scroll does not bubble, but it can be captured, so one listener sees every scroller.
  doc.addEventListener('scroll', onScroll, { capture: true, passive: true })
  doc.addEventListener('pointermove', onMove, { passive: true })
  return () => {
    doc.removeEventListener('scroll', onScroll, { capture: true })
    doc.removeEventListener('pointermove', onMove)
  }
}
