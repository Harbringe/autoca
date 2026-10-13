// The keyboard guide's contents, in the order a person wants them: the keys of the screen they are on first (marked "here"), then the
// "go to" jumps, then the ones that work everywhere. Pure, so the ordering, the counts and the search can be tested.

import { comboKeys, type Hotkey } from '@/lib/hotkeys'

export interface ShortcutCategory {
  id: string
  label: string
  /** True for the keys of the screen being looked at. */
  here: boolean
  items: Hotkey[]
}

const EVERYWHERE = 'Everywhere'
const GO_TO = 'Go to'

/** What the registry calls a group becomes what the guide calls it. */
const labelOf = (group?: string) => (!group || group === 'Global' ? EVERYWHERE : group === 'This client' ? GO_TO : group)

export function shortcutCategories(hotkeys: Hotkey[]): ShortcutCategory[] {
  const by = new Map<string, Hotkey[]>()
  for (const hotkey of hotkeys) {
    const label = labelOf(hotkey.group)
    by.set(label, [...(by.get(label) ?? []), hotkey])
  }
  const make = (label: string, here: boolean): ShortcutCategory => ({ id: label, label, here, items: by.get(label) ?? [] })
  const screens = [...by.keys()].filter((l) => l !== GO_TO && l !== EVERYWHERE).sort((a, b) => a.localeCompare(b))
  return [...screens.map((l) => make(l, true)), ...(by.has(GO_TO) ? [make(GO_TO, false)] : []), ...(by.has(EVERYWHERE) ? [make(EVERYWHERE, false)] : [])]
}

/** The categories narrowed to what matches the words typed: in what the key does, or in the keys themselves ("ctrl", "g l"). */
export function searchCategories(categories: ShortcutCategory[], query: string): ShortcutCategory[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return categories
  return categories
    .map((c) => ({
      ...c,
      items: c.items.filter((h) => {
        const hay = `${h.description} ${comboKeys(h.combo).join(' ')} ${c.label}`.toLowerCase()
        return words.every((w) => hay.includes(w))
      }),
    }))
    .filter((c) => c.items.length > 0)
}
