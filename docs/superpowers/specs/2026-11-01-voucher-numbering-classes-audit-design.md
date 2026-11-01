# Voucher numbering, voucher classes and the audit trail

Status: draft for the user's approval. Nothing here is built. Project 2 of the Tally-replacement roadmap.

## What is already true (checked in the code, 2026-11-01)

- **Numbering is already per voucher type.** `VoucherSequence` is keyed by client, financial year and voucher type; the book enforces
  one number per type per year (`uniq_voucher_number_per_book`). Sign-off can renumber to close gaps (`ChangeAction.RENUMBERED`).
  An earlier note in this project said there was "one series"; that was wrong.
- **Tally's own number is stored and never shown.** `TallyVoucher.tally_number` holds it; no API or screen exposes it, so an imported
  Purchase 138 appears as AutoCA's Purchase 1.
- **A firm's own Tally voucher types are folded into a standard type** (GST SALE counts as Sales), so their numbers merge into one series.
- **There is an entry-level audit trail** (`EntryChange`: who, when, why, the full before, append-only; removed entries are recoverable) with
  `GET journal-entries/{id}/changes`. There is a coarse per-request `AuditLog`. There is **no screen** that lists changes across the books,
  and **masters are not covered** (a ledger renamed, regrouped or deactivated; a party edited).
- **Voucher classes do not exist.**

## Why

A Tally user finds old records by voucher number, expects each series to look the way their firm numbers it, and expects to see who changed
what. Today they cannot search by their Tally number, cannot control the number's look, and cannot see a trail except one entry at a time.

## Goals

1. Show the Tally voucher number wherever a voucher is listed or opened (Day Book, party statement, ledger, bill, search), beside ours.
2. A client can set, per voucher type, a prefix and padding for how numbers read (for example `S/25-26/0001`), applied to new vouchers and
   shown on prints; the stored number stays an integer.
3. A firm's own voucher types keep their own names and their own numbering series, each with a parent standard type for accounting.
4. Voucher classes: a named preset for a voucher type (the ledgers and tax lines it fills in), so entering a common voucher is one choice.
5. An audit trail screen: every change to vouchers **and to masters** (ledgers, groups, parties, rules), filterable by date, person, type
   and ledger, showing before and after.

## Non-goals

- Changing numbers already given, except by the existing sign-off renumbering.
- Tally's "alteration vs deletion" report formats; the screen is ours.
- Per-user numbering series.

## Anti-goals

- A number that can repeat, skip silently, or change after sign-off without a trail.
- An audit trail that can be edited or that a firm cannot read.

## My calls (to be confirmed)

1. Tally's number is shown as a second small label ("Tally 138") only on imported vouchers, never in place of ours.
2. Prefix and padding are per client and per voucher type, with a default of no prefix and no padding, so nothing changes until chosen.
3. A firm's own voucher type becomes a first-class type with a name, a parent and its own sequence. Imported vouchers of that type join it,
   keeping their Tally number. (This changes the enum `VoucherType` into data; it is the largest piece.)
4. Voucher classes start with exactly what Tally's classes do for sales and purchase: preset party-side and tax ledgers. Others later.
5. Audit trail rows for masters are written by the same append-only mechanism as entry changes, in a new table; nothing is back-filled.

## Left to the builder

- The audit screen's layout and how long a before/after diff is shown inline.
- How the prefix is rendered on a print (project 3 owns printing).

## What I need from the user

- Whether your clients actually use voucher classes. If not, goal 4 drops out of this project.
- Whether a firm's own voucher types should get their own numbering (call 3), or stay merged with the standard type as now.
