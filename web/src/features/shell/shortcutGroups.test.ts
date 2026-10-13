import { describe, expect, it } from 'vitest'
import type { Hotkey } from '@/lib/hotkeys'
import { comboKeys as keyCaps } from '@/lib/hotkeys'
import { searchCategories, shortcutCategories } from './shortcutGroups'

const key = (combo: string, description: string, group?: string): Hotkey => ({ combo, description, group, run: () => {} })
const KEYS = [
  key('ctrl+k', 'Search clients, go to a screen, run an action'),
  key('?', 'Show keyboard shortcuts', 'Global'),
  key('g v', 'This client: Review', 'Go to'),
  key('g l', 'This client: Ledgers', 'Go to'),
  key('alt+arrowup', 'Up one level', 'This client'),
  key('j', 'Next row', 'Review'),
  key('p', 'Post this row', 'Review'),
  key('j', 'Next alert', 'Alerts'),
]

describe('the keyboard guide', () => {
  it('puts the keys of the screen first, then Go to, then Everywhere', () => {
    const c = shortcutCategories(KEYS)
    expect(c.map((x) => x.label)).toEqual(['Alerts', 'Review', 'Go to', 'Everywhere'])
    expect(c.map((x) => x.here)).toEqual([true, true, false, false])
    expect(c.find((x) => x.label === 'Everywhere')!.items).toHaveLength(2)
    // the client's own jumps are Go to keys, not a screen of their own
    expect(c.find((x) => x.label === 'Go to')!.items).toHaveLength(3)
  })

  it('leaves out a heading nothing is registered under', () => {
    expect(shortcutCategories([key('j', 'Next', 'Review')]).map((x) => x.label)).toEqual(['Review'])
  })

  it('writes keys as caps, with arrows as arrows', () => {
    expect(keyCaps('ctrl+k')).toEqual(['Ctrl', 'K'])
    expect(keyCaps('alt+arrowup')).toEqual(['Alt', '↑'])
    expect(keyCaps('g l')).toEqual(['G', 'L'])
    expect(keyCaps('shift+f6')).toEqual(['Shift', 'F6'])
  })

  it('searches what a key does, the keys, and the heading, all words needed', () => {
    const c = shortcutCategories(KEYS)
    expect(searchCategories(c, 'post').flatMap((x) => x.items.map((i) => i.description))).toEqual(['Post this row'])
    expect(searchCategories(c, 'ledgers').map((x) => x.label)).toEqual(['Go to'])
    expect(searchCategories(c, 'ctrl').flatMap((x) => x.items)).toHaveLength(1)
    expect(searchCategories(c, 'next row')).toHaveLength(1)
    expect(searchCategories(c, 'zzz')).toEqual([])
    expect(searchCategories(c, '  ')).toBe(c)
  })
})
