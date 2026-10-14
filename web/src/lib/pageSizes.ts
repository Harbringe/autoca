// How many rows each list shows on a page. A person can choose one number for every list, or a different one for a particular list; with
// neither chosen, each list keeps its own sensible size. Kept in this browser, like the other preferences, and read through a small store so
// the lists and the Preferences screen always agree.

import { useSyncExternalStore } from 'react'

export type PageSection = 'review' | 'daybook' | 'statements' | 'ledger' | 'parties' | 'partyList' | 'rules' | 'proposals' | 'alerts' | 'activity' | 'firm'

export const PAGE_SECTIONS: { id: PageSection; label: string; fallback: number }[] = [
  { id: 'review', label: 'Review queue', fallback: 10 },
  { id: 'daybook', label: 'Day Book', fallback: 10 },
  { id: 'statements', label: 'Statement rows', fallback: 10 },
  { id: 'ledger', label: 'A ledger’s entries', fallback: 10 },
  { id: 'parties', label: 'Parties found', fallback: 10 },
  { id: 'partyList', label: 'Parties', fallback: 10 },
  { id: 'rules', label: 'Rules', fallback: 10 },
  { id: 'proposals', label: 'Ledgers the assistant added', fallback: 10 },
  { id: 'alerts', label: 'Alerts', fallback: 10 },
  { id: 'activity', label: 'Activity log', fallback: 10 },
  { id: 'firm', label: 'Firm settings lists (people, clients)', fallback: 10 },
]

export const SIZE_CHOICES = [10, 25, 50, 100] as const

interface Chosen {
  all: number | null
  by: Partial<Record<PageSection, number>>
}

const KEY = 'autoca.pageSizes'
const listeners = new Set<() => void>()
const valid = (n: unknown): n is number => typeof n === 'number' && (SIZE_CHOICES as readonly number[]).includes(n)

function read(): Chosen {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? 'null') as { all?: unknown; by?: Record<string, unknown> } | null
    const by: Chosen['by'] = {}
    for (const s of PAGE_SECTIONS) if (valid(raw?.by?.[s.id])) by[s.id] = raw!.by![s.id] as number
    return { all: valid(raw?.all) ? raw.all : null, by }
  } catch {
    return { all: null, by: {} }
  }
}

let chosen = read()

function save(next: Chosen) {
  chosen = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // It still applies for this visit.
  }
  listeners.forEach((l) => l())
}

/** One size for every list, or null to let each keep its own. Choosing it clears the per-list choices, so "all" means all. */
export const setAllPageSize = (size: number | null) => save({ all: size, by: {} })

/** A size for one list, or null to follow the rest. */
export function setSectionPageSize(section: PageSection, size: number | null) {
  const by = { ...chosen.by }
  if (size === null) delete by[section]
  else by[section] = size
  save({ ...chosen, by })
}

/** What a list shows per page: its own choice, else the one for all lists, else its own default. */
export const pageSizeOf = (section: PageSection, from: Chosen = chosen): number =>
  from.by[section] ?? from.all ?? PAGE_SECTIONS.find((s) => s.id === section)!.fallback

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

export function usePageSize(section: PageSection): number {
  return useSyncExternalStore(subscribe, () => pageSizeOf(section), () => PAGE_SECTIONS.find((s) => s.id === section)!.fallback)
}

export function usePageSizeChoices(): Chosen {
  return useSyncExternalStore(subscribe, () => chosen, () => ({ all: null, by: {} }))
}
