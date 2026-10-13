// The assistant's ledger ideas for rows it was not sure enough to place: grouped by idea, so one decision covers every row that carries it.
// Free of React so it can be tested.

import type { Classification } from '@/api/types'

export interface Idea {
  key: string
  name: string
  group: string
  /** The client's ledger it can go into straight away, or null when the ledger has to be created first. */
  existingLedger: string | null
  rows: Classification[]
}

/** The ideas on rows that have no ledger yet, the one with the most rows first. A row a person placed, or that is posted, carries none. */
export function ideasOf(rows: readonly Classification[]): Idea[] {
  const by = new Map<string, Idea>()
  for (const r of rows) {
    const s = r.suggested_ledger
    if (!s || r.ledger || r.is_posted || r.method === 'REVIEWED') continue
    const key = s.existing_ledger ?? `new:${s.name.trim().toLowerCase()}`
    const idea = by.get(key) ?? { key, name: s.existing_name ?? s.name, group: s.group, existingLedger: s.existing_ledger ?? null, rows: [] }
    idea.rows.push(r)
    by.set(key, idea)
  }
  return [...by.values()].sort((a, b) => b.rows.length - a.rows.length || a.name.localeCompare(b.name))
}

/** Run `tasks` at most `limit` at a time, reporting each as it finishes. A task that throws is counted, and the rest carry on. */
export async function runLimited<T>(tasks: readonly (() => Promise<T>)[], limit: number, onEach?: (done: number, failed: number) => void): Promise<{ done: number; failed: number }> {
  let next = 0
  let done = 0
  let failed = 0
  async function worker() {
    while (next < tasks.length) {
      const task = tasks[next++]!
      try {
        await task()
        done += 1
      } catch {
        failed += 1
      }
      onEach?.(done, failed)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker))
  return { done, failed }
}
