# Import history from Tally: design

Date: 2026-10-17. Status: draft for review. Path: architectural (new subsystem that writes to the books of record).

## Purpose

A client who is new to AutoCA arrives with years of books in Tally. A firm should be able to bring that history in, so that:

1. the client's own ledgers, groups and parties are the chart (not names we invent);
2. every voucher is in the books as Tally had it (same date, number, lines);
3. sales and purchase vouchers exist as bills, with party, invoice number, GST, TCS and freight;
4. bank entries exist as statement rows, so the bank ledger and later reconciliation work;
5. the AI learns from the accountant's own decisions in that history (parties and rules).

This is for clients with **no AutoCA postings in the imported period**. It is not a way to compare Tally with AutoCA on the same period (that was done by hand for Mauli and is out of scope).

## Inputs

Two Tally exports, either optional:

| File | Tally export | What it gives |
|---|---|---|
| Masters | Export masters (ledgers, groups, opening balances) | Chart, groups, parties' GSTIN, opening balances. Already parsed by `ledger/tally_parse.py`. |
| Vouchers | Export vouchers in Tally's import XML (`<TALLYMESSAGE><VOUCHER ...>`, as in `sales.xml` and `purchase.xml`) | Every voucher type with its ledger lines, party, GST, items. |

The one-sided "ledger vouchers" report (`DSPVCH...`, as in `bank.xml`) and the GST report files are **not** inputs: they cannot make a balanced entry. GST files may later serve as a check.

All files are untrusted: `defusedxml`, no DTD or entities, size and count caps, control characters stripped before parsing, names that a spreadsheet would run as a formula are skipped, the type decided from the bytes. Same rules as the masters parser.

## Mapping

Voucher kind is decided from `VCHTYPE` / `VOUCHERTYPENAME`, then from the ledgers it touches.

| Tally voucher | Becomes | Notes |
|---|---|---|
| Sales, Purchase, Credit Note, Debit Note | `JournalEntry` (kind VOUCHER) + `Bill` | Through the existing `ledger.billing` planner so GST, TCS (`TCS Receivable`) and freight (`Freight & Cartage`) follow the app's rules. Item lines become stock entries only if inventory is on for the client. |
| Payment, Receipt, Contra with a bank ledger | `StatementTransaction` on that bank account + `JournalEntry` (kind BANK) with `source_transaction` | Bank account matched by ledger name or account number. If no bank account matches, the person maps it in the preview, or it is posted as a journal. |
| Journal, and Payment/Receipt/Contra with no bank ledger (cash) | `JournalEntry` (kind JOURNAL) | |
| Cancelled, optional, deleted | skipped, listed | |

- Voucher numbers are kept as written. `uniq_voucher_number_per_book` is per firm, client, year and type, so a clash is detected in the preview and listed, not overwritten.
- Each voucher is identified by its Tally `GUID`/`REMOTEID`, stored on the entry. A second upload of the same file imports nothing new.
- A voucher posts all-or-nothing. It is skipped, with the reason, if it does not balance, names a ledger that is not in the chart (after masters are applied), has a date outside the chosen range, or fails the existing posting checks.
- Ledgers named only in vouchers (no masters file) are created in the group their Tally group implies, or in a "needs a group" list.
- Parties: debtors and creditors become `Party` rows with GSTIN from the voucher (`PARTYGSTIN`); the same party under two spellings is offered for merge, never merged silently.

## Learning

Each imported bank entry is treated as a decision by a person: the accountant chose the ledger.

- Parties come from debtor/creditor ledgers and their bill history, with their usual ledger.
- Rules are proposed from the bank history using `classify.scoring` (Wilson lower bound, specificity prior, base-rate): a payee or narration that went to one ledger most of the time gets a rule; one that went to many only suggests; a one-word payee only suggests, as already decided.
- No imported rule auto-posts. Imported rules carry source "Tally history" and show in the Rules screen, so a firm can review or delete them as a batch.
- Learning runs after the vouchers are posted, never as part of the posting itself, so a learning failure cannot undo books.

## Flow and screen

New screen "Import history from Tally" per client.

1. **Upload** masters and/or vouchers. Choose the date range (default: the whole file). Nothing is written except a staged run.
2. **Preview**: counts by voucher type; date range; new ledgers and parties; bank accounts found and their mapping; skipped vouchers with reasons; clashes; opening balance check (Tally's balance at the range start against the opening we will set).
3. **Confirm**: runs as a background job with progress. One atomic transaction per voucher batch, all tied to one import run.
4. **Undo**: the whole run can be reversed while nothing posted after it depends on it; otherwise the screen says which later entries block it.

Staging follows `LedgerImportRun`: staged rows only, no file kept, expiry, a fingerprint of the client's chart at preview time (a confirm against a changed chart is refused).

## Safety

- Refuses a date range that already has any AutoCA posting for the client, and any locked financial year (`_refuse_if_locked`).
- Only roles that can post (`_require_rights`); everything firm-scoped under row-level security.
- Entries are append-only; imported entries get a marker (`EntryMarker`) so reports can show "imported from Tally". Corrections after import use the normal supersede path.
- Caps on file size, vouchers per run, lines per voucher, name lengths.
- No Tally data in logs beyond counts and voucher numbers.
- Real client data is never committed; tests use synthetic files.

## Phases

1. **Masters screen, plus sales, purchase, credit/debit note and journal vouchers.** Chart, parties, bills, entries. The masters backend exists; this adds the screen and the voucher parser/planner.
2. **Bank vouchers as statement rows**, with bank-account mapping and the opening-balance check.
3. **Learning** of parties and rules from the history.

Each phase is released and checked on its own.

## Testing

- Pure parser tests with synthetic XML for each voucher type, bad inputs (entities, huge files, control characters, unbalanced vouchers, cancelled).
- Planner tests: each voucher type to the expected lines, including GST, TCS, freight, round-off, reverse charge.
- DB tests (CI): idempotent re-run, clash with existing numbers, refusal on a range with postings, atomicity, undo, row-level security isolation between firms.
- Learning tests on a synthetic history: proportion cases (one ledger 95%, split, one-word payee).
- Web tests for the preview and confirm states.
- A manual check on a real export, run by the user, before release.

## Open questions for the plan stage

1. **Statement placeholder.** `Statement` needs a `Document`, balances and a parser name. Tally-sourced rows need either a synthetic statement marked "from Tally" or a nullable link; to be chosen when reading `banking/ingest.py` and the Document model.
2. **Inventory.** Whether item lines import as stock in phase 1 or are ignored with a note.
3. **Voucher numbering in the same year as AutoCA's own series.** Imported numbers and AutoCA's `VoucherSequence` must not collide for the first new voucher after the range.
4. **Multi-company or multi-year files.** Assumed one company, one range per run; the preview should refuse a file with several companies.
5. **Export instructions.** The exact Tally menu path for the vouchers export, to be written into the screen's help text after the user confirms it on their version.
6. **Opening balances.** Whether to take them from the masters file, from the first year's brought-forward, or to compute them from vouchers.
