# Moving a firm's Tally history in: large files, the guided move, and the remaining import gaps

Status: draft for the user's approval. Nothing here is built. Project 1 of the Tally-replacement roadmap (the order: 1 import and large
files, 2 voucher numbering/classes/audit trail, 3 printing, 4 inventory, 5 statutory returns, 6 reports and cost centres/budgets,
7 banking extras, 8 manufacturing; keyboard-first entry runs alongside all of them).

## Why

The aim is a replacement for Tally, so a firm must be able to move its books in, a year or a few months at a time, and keep working
from them. What is built (the queue, the stored files, JSON and XML vouchers, voucher types) works for a month. A real firm has years
of history in exports that are far larger, and posting that history today would time out.

Measured on a real export: one month of one client is 4.6 MB of JSON (362 vouchers); a year is about 12 times that, so about 55 MB, and
posting 362 vouchers took about 40 seconds on the live database. At those rates a five-year move is about 275 MB of exports and several
hours of writing, none of which fits in one web request or under the 10 MB limit.

## Goals

- A firm can hand over a year's export, or five of them, and everything is read, held in the queue, checked, and posted without a
  request timing out or a person watching a screen.
- Each import in the queue is small enough to review: a file is split into one queued import per month, each postable and undoable on
  its own, with "Post all" for the lot.
- The move is guided: ledger list, voucher types, then vouchers by financial year, with a clear record of what has been brought in and
  what is still to do.
- What was posted can be checked against Tally's own figures (the trial balance), so the accountant can sign it off.

## Non-goals

- Importing things the app cannot hold yet. Stock items and units belong to project 4 (inventory), cost centres and budgets to
  project 6, payroll masters to project 5. Their import arrives with them.
- Writing back to Tally.
- Reading Tally's own data files (the TDL or `.900` data). Only its exports.

## Anti-goals

- A move that silently drops or double-counts vouchers. Every voucher is posted, skipped with a reason, or refused; the totals tie to
  the file.
- Anything that changes books already signed off.

## Constraints

- Exports are read in a background worker, never in a web request (the proxy limit is 60 seconds).
- The stored file is the evidence; the posting reads from the plan made from it (as now).
- A voucher already imported (by Tally's id) is never written twice.
- Memory: a worker must not hold a 100 MB file as parsed objects at once for XML (stream it). JSON is read whole, so JSON has a
  lower limit; larger exports must be split by period in Tally.

## What is decided (by the user, in conversation)

- The order of the roadmap above.
- Entries already in a period are the accountant's decision, not a refusal (built).
- A queue of imports with the file kept and background posting with progress (built and live).

## My calls (to be confirmed)

1. **Size limit.** 150 MB per file for XML, 100 MB for JSON; the 10 MB limit is lifted for vouchers (it stays for ledger lists and voucher
   types, which are small).
2. **Splitting.** One queued import per calendar month of the voucher dates. A month, because it matches how an accountant reviews and closes
   books, and keeps each import to a few thousand vouchers for a typical firm (my estimate; the measured month was 362). Splitting is by date, so a voucher is in
   exactly one import.
3. **Reading in the background.** Uploading a vouchers file stores it, answers at once ("being read"), and a worker reads it and creates
   the monthly imports, with progress. The same worker queue as posting.
4. **Post all.** A button that queues the months in date order, one at a time (the books are written oldest first, as Tally shows them).
5. **Check against Tally.** The accountant uploads Tally's trial balance for the same period (an export), and the screen lists each ledger
   where Tally's closing balance and ours differ. Differences are shown, never fixed automatically.
6. **Reversing journals** stay held back for now, with the reason shown. A later change may import them with their reversing entry.

## Left to the builder

- How the staged plan of a very large month is stored (the current JSON column is fine for a month; if it is not, a rows table).
- The exact screen for the guided move and the "imports by month" view.
- Whether the trial-balance export is JSON or XML (to be read from a real sample, as the other readers are).

## What I need from the user

- A real Tally export of the **ledger list** (Masters > Ledgers) and of the **trial balance**, in JSON or XML, from a company with real
  entries. The readers for these were written without a real file and are marked unverified; the move cannot be called done until they
  have been run against one.
- A decision on the "My calls" above, or a different choice.
