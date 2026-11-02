// The keys that belong to one screen, listed in one place so the keyboard guide on the Preferences page can show every screen's keys, not only
// those of the screen you are on (a screen registers its keys only while it is open). The keys that work everywhere are registered by the shell
// and need no entry here. A test (shortcutCatalog.test.ts) reads the source and fails when a key is registered by a screen but missing from this
// list, so the two cannot drift apart.

import type { Hotkey } from '@/lib/hotkeys'

type Entry = Pick<Hotkey, 'combo' | 'description' | 'group'>

export const SCREEN_KEYS: Entry[] = [
  { combo: 'n', description: 'New client', group: 'Clients' },

  { combo: 'u', description: 'Upload a bank statement', group: 'This client' },
  { combo: 'g o', description: 'This client: Overview', group: 'Go to' },
  { combo: 'g v', description: 'This client: Review', group: 'Go to' },
  { combo: 'g l', description: 'This client: Ledgers', group: 'Go to' },
  { combo: 'g k', description: 'This client: Sign-off', group: 'Go to' },
  { combo: 'g e', description: 'This client: Client profile', group: 'Go to' },
  { combo: 'g m', description: 'This client: Parties & rules', group: 'Go to' },
  { combo: 'g y', description: 'This client: Day Book', group: 'Go to' },
  { combo: 'g i', description: 'This client: Stock items', group: 'Go to' },
  { combo: 'g q', description: 'This client: Cheques', group: 'Go to' },
  { combo: 'g a', description: 'This client: Audit trail', group: 'Go to' },
  { combo: 'g x', description: 'This client: TDS', group: 'Go to' },
  { combo: 'g p', description: 'This client: Payroll', group: 'Go to' },
  { combo: 'f8', description: 'New sales voucher', group: 'Voucher entry' },
  { combo: 'f9', description: 'New purchase voucher', group: 'Voucher entry' },
  { combo: 'ctrl+s', description: 'Save the voucher', group: 'Voucher entry' },

  { combo: 'j', description: 'Next row', group: 'Review' },
  { combo: 'arrowdown', description: 'Next row', group: 'Review' },
  { combo: 'k', description: 'Previous row', group: 'Review' },
  { combo: 'arrowup', description: 'Previous row', group: 'Review' },
  { combo: '/', description: 'Search the queue', group: 'Review' },
  { combo: 'x', description: 'Tick the current row for posting', group: 'Review' },
  { combo: 'l', description: 'Choose the ledger', group: 'Review' },
  { combo: 'enter', description: 'Place the row in the chosen ledger', group: 'Review' },
  { combo: 'p', description: 'Post this row', group: 'Review' },

  { combo: 'j', description: 'Next alert', group: 'Alerts' },
  { combo: 'k', description: 'Previous alert', group: 'Alerts' },
  { combo: 'o', description: 'Open the selected alert', group: 'Alerts' },

  { combo: 'n', description: 'Invite a person', group: 'Team' },
]

/**
 * The keys registered right now together with every screen's keys, once each. A key a screen has registered keeps its own entry (so it
 * runs); one from the list that no open screen has registered is shown for reading, and does nothing here.
 */
export function withAllScreens(registered: Hotkey[]): Hotkey[] {
  const same = (a: Entry, b: Entry) => a.combo === b.combo && a.description === b.description && (a.group ?? 'Global') === (b.group ?? 'Global')
  const extra = SCREEN_KEYS.filter((k) => !registered.some((r) => same(r, k))).map((k) => ({ ...k, run: () => {} }))
  return [...registered, ...extra]
}
