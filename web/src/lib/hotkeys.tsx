// Keyboard shortcuts, in one registry.
//
// CAs who came up on Tally work from the keyboard, so every screen registers
// what its keys do here and the "?" sheet lists them. A shortcut is registered
// by the screen that owns it and disappears with the screen, so the sheet only
// ever shows keys that work right now.
//
// Combos are written "ctrl+k", "alt+c", "shift+a", "?" or "g d" (a two-key
// sequence). Plain keys are ignored while a text field has focus; combos that
// hold ctrl, alt or meta are not, because typing never produces those.

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export interface Hotkey {
  combo: string
  description: string
  /** A heading in the shortcut sheet; "Global" for the ones every screen has. */
  group?: string
  run: (event: KeyboardEvent) => void
}

interface Registry {
  register: (hotkey: Hotkey) => () => void
  list: () => Hotkey[]
  subscribe: (listener: () => void) => () => void
}

const Ctx = createContext<Registry | null>(null)

const SEQUENCE_WINDOW_MS = 900

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  // A ticked box has no text to type into, so shortcuts still work from it.
  if (target instanceof HTMLInputElement && ['checkbox', 'radio', 'button', 'submit'].includes(target.type)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/** "Ctrl+Shift+K" from a keydown, in the same spelling the registry uses. */
export function comboOf(event: KeyboardEvent): string {
  const parts: string[] = []
  if (event.ctrlKey || event.metaKey) parts.push('ctrl')
  if (event.altKey) parts.push('alt')
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key.toLowerCase()
  // Shift is part of a symbol's identity ("?"), so only letters and named keys carry it.
  if (event.shiftKey && (key.length > 1 || /[a-z]/.test(key))) parts.push('shift')
  parts.push(key)
  return parts.join('+')
}

export function HotkeyProvider({ children }: { children: ReactNode }) {
  const registry = useRef<Registry | null>(null)
  if (!registry.current) {
    const entries = new Set<Hotkey>()
    const listeners = new Set<() => void>()
    const changed = () => listeners.forEach((l) => l())
    registry.current = {
      register(hotkey) {
        entries.add(hotkey)
        changed()
        return () => {
          entries.delete(hotkey)
          changed()
        }
      },
      list: () => [...entries],
      subscribe(listener) {
        listeners.add(listener)
        return () => listeners.delete(listener)
      },
    }
  }
  const reg = registry.current

  useEffect(() => {
    let pending: { key: string; at: number } | null = null

    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat) return
      const combo = comboOf(event)
      const modified = combo.includes('ctrl+') || combo.includes('alt+')
      if (!modified && isTyping(event.target)) return
      // A dialog is its own small world: keys pressed in it are for it, not for the screen behind.
      if (event.target instanceof HTMLElement && event.target.closest('[role="dialog"], [role="alertdialog"]')) return
      // Enter and Space on a focused button or link already mean "press this"; a shortcut on top would act twice.
      if ((combo === 'enter' || combo === ' ') && event.target instanceof HTMLElement && event.target.closest('button, a, [role="option"]')) return
      if (['shift', 'control', 'alt', 'meta'].includes(event.key.toLowerCase())) return

      const hotkeys = reg.list()
      // The second key of a "g d" sequence.
      if (pending && Date.now() - pending.at < SEQUENCE_WINDOW_MS) {
        const sequence = `${pending.key} ${combo}`
        const hit = hotkeys.find((h) => h.combo === sequence)
        pending = null
        if (hit) {
          event.preventDefault()
          hit.run(event)
          return
        }
      }
      const hit = hotkeys.find((h) => h.combo === combo)
      if (hit) {
        event.preventDefault()
        hit.run(event)
        return
      }
      if (!modified && hotkeys.some((h) => h.combo.startsWith(`${combo} `))) pending = { key: combo, at: Date.now() }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [reg])

  return <Ctx.Provider value={reg}>{children}</Ctx.Provider>
}

/** Register a shortcut for as long as the calling component is mounted. */
export function useHotkey(combo: string, description: string, run: (event: KeyboardEvent) => void, group = 'Global') {
  const reg = useContext(Ctx)
  const latest = useRef(run)
  latest.current = run
  useEffect(() => {
    if (!reg) return
    return reg.register({ combo, description, group, run: (e) => latest.current(e) })
  }, [reg, combo, description, group])
}

/** Everything registered right now, for the shortcut sheet. */
export function useHotkeyList(): Hotkey[] {
  const reg = useContext(Ctx)
  const [version, bump] = useState(0)
  useEffect(() => reg?.subscribe(() => bump((n) => n + 1)), [reg])
  // `version` is what changes when something registers or leaves; the list is read fresh each time.
  return useMemo(() => reg?.list() ?? [], [reg, version]) // eslint-disable-line
}

/** "ctrl+k" -> ["Ctrl", "K"], for showing in a <Kbd>. */
export function comboKeys(combo: string): string[] {
  return combo.split(/[+ ]/).map((k) => (k.length === 1 ? k.toUpperCase() : k.charAt(0).toUpperCase() + k.slice(1)))
}
