// Enter moves to the next field, the way Tally's entry screens do, and the last field's Enter saves.
//
// Only plain one-line fields take part: a text area, a button, a link, a checkbox, an open pick-list and anything the field itself already
// handles (a key it marked as handled) are left alone, so Enter still adds a line or picks an option where that is what it means.

const FIELD = 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]):not([disabled]):not([readonly]), select:not([disabled])'

function visible(el: HTMLElement): boolean {
  if (el.closest('[hidden], [aria-hidden=true]')) return false
  const style = getComputedStyle(el)
  return style.display !== 'none' && style.visibility !== 'hidden'
}

/** Call from a form's keydown. Returns true when it moved focus or saved, so the caller knows the key was used. */
export function advanceOnEnter(event: KeyboardEvent | React.KeyboardEvent, form: HTMLFormElement): boolean {
  if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return false
  if ('defaultPrevented' in event && event.defaultPrevented) return false
  const target = event.target as HTMLElement
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return false
  // A pick-list that is open uses Enter to choose; leave it to the list.
  if (target.getAttribute('aria-expanded') === 'true') return false
  const fields = [...form.querySelectorAll<HTMLElement>(FIELD)].filter(visible)
  const at = fields.indexOf(target)
  if (at < 0) return false
  event.preventDefault()
  const next = fields[at + 1]
  if (next) {
    next.focus()
    if (next instanceof HTMLInputElement) next.select()
  } else {
    form.requestSubmit()
  }
  return true
}
