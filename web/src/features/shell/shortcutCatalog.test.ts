import { describe, expect, it } from 'vitest'
import type { Hotkey } from '@/lib/hotkeys'
import { SCREEN_KEYS, withAllScreens } from './shortcutCatalog'

// Every source file, as text: used to find the keys a screen registers.
const SOURCES = import.meta.glob('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe('the list of every screen’s keys', () => {
  // useHotkey('combo', 'Description', () => ..., 'Group') with literal text; the shell's own keys (no group, or a computed key) are not screen keys.
  const found: { combo: string; description: string; group: string }[] = []
  for (const [file, text] of Object.entries(SOURCES)) {
    if (file.includes('.test.') || file.endsWith('/lib/hotkeys.tsx')) continue
    // The shell's own keys work on every screen and are registered once there; the rest belong to one screen.
    if (file.includes('/features/shell/')) continue
    for (const segment of text.split('useHotkey(').slice(1)) {
      const head = segment.match(/^\s*'([^']+)',\s*'([^']+)',/)
      const groups = [...segment.matchAll(/,\s*'([A-Za-z ]+)'\s*\)/g)]
      if (head && groups.length) found.push({ combo: head[1]!, description: head[2]!, group: groups[0]![1]! })
    }
  }

  it('finds the keys screens register (the check is looking at something)', () => {
    expect(found.length).toBeGreaterThan(15)
  })

  it('has every key a screen registers with a group of its own', () => {
    const missing = found.filter((f) => !SCREEN_KEYS.some((k) => k.combo === f.combo && k.description === f.description && k.group === f.group))
    expect(missing).toEqual([])
  })

  it('shows each key once: a registered key is not repeated from the list', () => {
    const registered: Hotkey[] = [{ combo: 'j', description: 'Next row', group: 'Review', run: () => {} }]
    const all = withAllScreens(registered)
    expect(all.filter((k) => k.combo === 'j' && k.group === 'Review')).toHaveLength(1)
    expect(all.some((k) => k.group === 'Alerts' && k.combo === 'o')).toBe(true)
  })
})
