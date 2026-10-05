# Party accounting, phase 1

Status: design for review. Nothing here is built. Written 2026-10-05.

Decided by the user (2026-10-05): **AutoCA is the final books of record** (not a feeder for Tally), **party-wise accounting is approved**, and the larger aim is that every document a CA firm receives reconciles into one set of books. This note is phase 1 of that: the foundation. Phases 2 onward (invoice reading, GST tie-in, assets, payroll, the close screen) are outlined in section 13 and each gets its own design.

Things marked **(decision)** are open and need an answer before or during the build. Each has a recommendation.

## 1. The problem, in one example

A client buys goods from Ravi Traders: invoice of 1 Oct, 1,00,000 plus 18,000 GST, total 1,18,000. They pay on 20 Oct by NEFT.

Today AutoCA sees only the bank line, and books `Dr Purchases 1,18,000 / Cr Bank 1,18,000` on 20 Oct. So:

- the 18,000 GST is buried in Purchases, never reaches an input-tax ledger, and cannot be checked against GSTR-2B;
- an invoice dated 28 March and paid in April is not in the March books at all, so the year's expenses and liabilities are wrong;
- there is no "Ravi Traders" balance, so "what do we owe him?" cannot be answered, and neither can "what does this customer owe us?".

After this phase:

- 1 Oct, **Purchase voucher**: `Dr Purchases 1,00,000 / Dr Input GST 18,000 / Cr Ravi Traders 1,18,000`.
- 20 Oct, bank line: `Dr Ravi Traders 1,18,000 / Cr Bank 1,18,000`, **allocated to that bill**.

Ravi's account now shows what is owed and clears to zero on payment. An unpaid invoice stays visible as a balance. The input GST is in its own ledger.

## 2. What exists today (facts from the code)

| Thing | State |
|---|---|
| `classify.Party` | Exists. Role (supplier, customer, both, other), encrypted GSTIN with a blind-index hash, `tds_section`, `rcm_default`, aliases, party bank accounts. Deliberately **not** a ledger ("the ledger says what kind of expense; the party says who"). |
| `JournalLine.party` | Exists, nullable. The party is a tag on a line, not an account. |
| `LedgerGroup.DEBTOR / CREDITOR` | Exist. The standard chart seeds one `Sundry Debtors` and one `Sundry Creditors` ledger, plus `Credit Card Payable`. |
| Voucher types | Payment, Receipt, Contra, Journal only. |
| `JournalEntry` | Append-only. Every entry carries `source_transaction`, a **bank statement row**. Entries have no other kind of source. |
| Editing, removing, correcting an entry | `revise_in_place`, `remove_entry` and `correct` all read `entry.source_transaction.classification`. They only work for bank-sourced entries. |
| Sign-off | `ledger/books.py` renumbers vouchers per (financial year, voucher type) generically, so a new voucher type is handled without change. Signed-off entries are immutable in the database. |
| Standard chart | One `GST Paid` ledger and `TDS Payable`. **No Input CGST/SGST/IGST, no Output GST, no round-off.** |
| TDS | A section code on the line only. No TDS amount is computed or posted. |
| Openings | `LedgerOpening`: one signed figure per ledger per financial year. No bill-wise openings. |
| GST (`gst/`) | Self-contained. Compares registers with GSTR-2B and never reads the ledger. |
| Production data | The AWS database is new and holds no real client books. Only dev and synthetic data exist, so migration risk is mostly to code and tests, not to clients. |

## 3. The central choice **(decision 1)**

How should a supplier or customer appear in the books?

**A. One ledger per party (Tally's model). Recommended.** Each `Party` gets its own `LedgerAccount` under Sundry Creditors or Sundry Debtors, linked by a new `Party.ledger`. The trial balance lists every creditor and debtor by name. `JournalLine.party` is also set, so existing party tags keep meaning.

**B. One control ledger plus a party sub-ledger.** A single "Sundry Creditors" ledger; each line tagged with its party; per-party balances come from summing tagged lines.

Why A:

- It is what a CA expects. In Tally the trial balance shows each creditor, and "ledger" and "party" are the same thing to the user.
- The planned Tally chart import already brings in each supplier and customer as one ledger, with `ISBILLWISEON`. Under A they simply link to a `Party`; under B they would have to be collapsed.
- Every existing report, the ledger view, and the sign-off all work per ledger already, so A needs no change to them.
- The classifier's rule "never open a ledger named after a person" does not clash: party ledgers are created by the system from a `Party`, not proposed by the model.

The cost of A: a client can have hundreds of ledgers, so the ledger picker must stop listing party ledgers by default (they are chosen through the party, not the chart). That is a UI rule, not a data problem.

B is less work to build but moves away from how the firm already thinks, and would make the trial balance less useful. I recommend A.

**Sub-decision (decision 2): a party that is both supplier and customer.** Recommendation: one ledger, in the group of the role it was created with, shown with a net balance, and bills of both directions listed separately in the outstanding report. Changing its group is allowed and only moves which side of the balance sheet the net lands on.

## 4. Data model

### 4.1 Party ledger link
- `classify.Party.ledger`: nullable one-to-one to `LedgerAccount`. Created on demand the first time a party is used in a voucher or settlement, the same pattern as `contra_ledger_for`. Group is CREDITOR for suppliers, DEBTOR for customers, per decision 2 for both. The ledger name is the party's canonical name; a clash gets the GSTIN's last four digits.
- Not backfilled in bulk. A party gets its ledger when first needed.

### 4.2 Voucher types
Add `PURCHASE`, `SALES`, `DEBIT_NOTE`, `CREDIT_NOTE` to `VoucherType`. Each has its own numbering series per financial year, which `VoucherSequence` already supports. Debit and credit notes are in phase 1 because returns are routine; without them every return needs a manual journal.

### 4.3 Bills
A new `ledger.Bill` row for each invoice, note or opening balance that a party owes or is owed:

- firm, client, `party`, `kind` (PURCHASE, SALES, DEBIT_NOTE, CREDIT_NOTE, OPENING, ADVANCE);
- `reference` (the supplier's or our invoice number), `bill_date`, optional `due_date`;
- `taxable_paise`, `cgst_paise`, `sgst_paise`, `igst_paise`, `cess_paise`, `round_off_paise`, `tds_paise`, `total_paise` (what the party is owed or owes);
- `entry`: the journal entry that booked it (one-to-one, null for an opening bill that has only a ledger opening behind it);
- `document`: optional link to the uploaded invoice file (used from phase 2).

A bill is a fact and is never edited after it is posted. Correcting one is a correcting entry, using the existing mechanism. Whether a bill is open, part-settled or settled is **computed from its allocations**, never stored, so it cannot drift.

Uniqueness: one bill per (party, kind, reference, financial year). A duplicate invoice number from the same supplier is refused with a clear message. This is the check that catches a supplier's invoice being booked twice.

### 4.4 Allocations
A new `ledger.BillAllocation` ties part of a journal line on a party ledger to a bill:

- `line` (the settling journal line), `bill`, `amount_paise` (positive), `kind` (AGAINST_BILL, ON_ACCOUNT, ADVANCE);
- an ON_ACCOUNT or ADVANCE allocation has no bill, and is itself a party balance waiting to be applied to a later bill.

Rules, enforced in the service layer and by a deferred database check: a bill's allocations never exceed its total; a line's allocations never exceed its amount; every allocation is for the same client, party and ledger as its line.

### 4.5 Entry sources
`JournalEntry` gains a second kind of source, because a purchase voucher has no bank row:

- keep `source_transaction` (bank rows) as it is;
- add `entry_kind` (BANK, VOUCHER, JOURNAL), default BANK, with `db_default`, because the repo's migration guard requires one on any new NOT NULL column;
- `Bill.entry` points the other way, so `JournalEntry` gains nothing else.

Editing and removal get a second path. `revise_in_place`, `remove_entry` and `correct` check `entry_kind`: a bank entry behaves exactly as today; a voucher entry is revised or removed through the bill (removing the entry removes its allocations and bill, before sign-off only).

### 4.6 Database safety
New tables follow the existing pattern: row-level security through `rls_operations`, `firm` and `client` carried on every row, composite foreign keys so a bill and its party cannot belong to different clients (the pattern of migration `0010`), grants for the app role, and no `UPDATE` once the books are signed off. The balance trigger on journal entries is unchanged, because a purchase voucher is an ordinary balanced entry.

## 5. Posting rules

All amounts are whole paise. Every entry balances, and the existing trigger enforces it.

### Purchase voucher
```
Dr  Purchases / expense / asset ledger     taxable value (one line per head)
Dr  Input CGST + Input SGST  (or Input IGST)
Dr  Round-off                               (if the invoice rounds)
Cr  Party ledger (supplier)                 total, less TDS if deducted here
Cr  TDS Payable                             TDS, if deducted here
```
**Reverse charge (RCM):** the supplier is credited only the taxable value, and the GST is booked as `Dr Input GST (RCM)` and `Cr GST Payable (RCM)`, so it nets to nothing in the books and is picked up in the return. `Party.rcm_default` and the line `rcm` flag already exist.

### Sales voucher
```
Dr  Party ledger (customer)                 total
Cr  Sales / service income                  taxable value
Cr  Output CGST + Output SGST  (or Output IGST)
Cr  Round-off                               (if the invoice rounds)
```

### Debit and credit notes
A purchase return is a **debit note**: `Dr Party (supplier) / Cr Purchases / Cr Input GST`. A sales return is a **credit note**: `Dr Sales / Dr Output GST / Cr Party (customer)`. Each is allocated against the bill it reverses.

### Settlement by a bank line
`Dr Party ledger / Cr Bank` for a payment, `Dr Bank / Cr Party ledger` for a receipt, with allocations against the bills it clears. A payment can clear several bills, part of one bill, or none yet (on account or advance).

### Opening
A party's opening balance stays a `LedgerOpening` figure. Optional bill-wise openings (`kind=OPENING` bills) split it into invoices, so ageing is correct from day one. The bill-wise openings must add up to the ledger opening, and the import refuses them if they do not.

### TDS **(decision 3)**
The law deducts at the earlier of credit and payment. Recommendation: **deduct when the bill is booked** (the purchase voucher above) as the default for sections that apply on credit, with the amount **typed by the CA** in phase 1 (no automatic computation of thresholds yet), and TDS at payment only for payments with no bill (advances, on account). This needs a CA's confirmation, since it is the firm's own practice that matters.

### GST ledgers **(decision 4)**
The standard chart has one `GST Paid` ledger. A real set of books needs Input CGST, Input SGST, Input IGST, Output CGST, Output SGST, Output IGST, RCM payable, and Round-off. Recommendation: add them to the standard ledgers (group DUTIES_AND_TAXES), created for a client the first time a voucher needs them, and leave `GST Paid` alone for existing data. Whether the supplier's GSTIN state decides CGST/SGST versus IGST is **not** computed in phase 1: the CA enters the split as printed on the invoice, and phase 2 adds the place-of-supply check.

## 6. Bank lines against bills

Today the classifier proposes a ledger for a bank line. The change:

1. When a bank line resolves to a party (it already does, through aliases, GSTIN and bank-account matches), the proposal becomes **that party's ledger plus an allocation suggestion**, not an expense head.
2. A matcher proposes the allocation, in order: an open bill with exactly this amount; a set of open bills summing to it (same party, oldest first); an amount that equals a bill less the party's TDS; otherwise on account.
3. **Nothing is auto-posted to a party ledger.** A person confirms every settlement in phase 1, even when the matcher is sure. This is stricter than today's auto-post, deliberately, because a wrong allocation is invisible in the totals (the ledger still balances) and only shows later as the wrong party owing the wrong amount.
4. A payment with no bill and no party is unchanged: it goes to an expense head, as today. A CA decides per payment whether an unmatched supplier payment is **direct expense** (a reason is recorded), **on account** (advance), or **needs invoice** (left open, listed as a missing document).
5. `revise_in_place` and `remove_entry` delete and recreate the allocations along with the lines. Mirror logic (own-account transfers and loans) is untouched, because a party ledger is neither a bank nor a cash ledger.

## 7. Reports

New, per client and financial year:

- **Outstanding payables and receivables**, bill-wise, with ageing (0-30, 31-60, 61-90, over 90 days from bill date or due date).
- **Party statement of account**: every voucher and settlement for one party with a running balance, printable to send to the party.
- **Creditors and debtors control check:** for each party, the sum of its open bills must equal its ledger balance (including openings and on-account amounts). A difference is an open item. This is the first real control-account reconciliation, and the pattern the later phases reuse.

The trial balance, profit and loss and balance sheet need no change. Party ledgers are ordinary DEBTOR and CREDITOR ledgers and the existing group sets already put them on the correct side.

## 8. API and screens

API: parties with balances; post a purchase, sales, debit-note or credit-note voucher; list and edit bills before sign-off; settle a bank line (confirm allocation); the three reports above. Every endpoint follows the existing firm and role permissions and the client-assignment rule, and states its error codes.

Screens (web): a **Parties** page (balances, open bills, statement); a **voucher entry** form for purchase and sales (party, invoice number, date, heads, GST split, TDS, round-off, with a live balance check); the **Outstanding** report; and in the bank review, a suggested-bills panel on any line that resolves to a party. A CSV import for a batch of invoices comes with phase 1d, since before invoice reading exists the firm needs a quick way to get invoices in.

## 9. Existing data and migration

- Production holds no client books. Dev, tests and the synthetic QA firm do.
- No entry is rewritten. Posted entries keep their lines and their party tags. Party ledgers are created lazily.
- Tally chart import links each Sundry Creditor and Sundry Debtor ledger to a `Party` by normalised name (creating the party if missing), carries `ISBILLWISEON`, and reads GSTIN where Tally has it.
- New columns carry database defaults, as the migration guard requires, so the previous release keeps working while a deploy is in flight.

## 10. What could go wrong, and the guard for each

| Risk | Guard |
|---|---|
| GST counted twice (once in a bill, once from the bank line) | Settlement posts `Dr Party / Cr Bank` only; the tax is only ever in the bill. A test posts the Ravi example and asserts the GST ledger balance. |
| An invoice booked twice | Uniqueness on party, kind, reference and year. |
| A settlement allocated to the wrong bill | Human confirmation on every settlement; allocations cannot exceed bill or line. |
| Voucher numbers shift at sign-off | `Bill.reference` is the supplier's number and is separate from the firm's voucher number, which renumbering may change. |
| A voucher entry reaching the bank-only edit code | `entry_kind` check; tests for edit, remove and correct on both kinds. |
| Rounding drift between bill total and ledger | Totals are checked to the paisa at posting; a bill that does not add up is refused. |
| Ledger picker flooded with party ledgers | Hidden from the chart picker by default; reached through the party. |
| AI classifying a bill payment as an expense | The party-first rule in section 6 puts the party ledger first; a regression test per supplier role. |

## 11. Tests

Pure unit tests for posting-rule arithmetic (purchase, sales, RCM, TDS, notes, round-off); database tests, run in CI, for the Ravi example end to end in both directions, part payments, over-allocation refused, duplicate invoice refused, on-account and advance application, edit and remove before sign-off, sign-off immutability of bills and allocations, and renumbering at sign-off. Isolation tests: another firm cannot see or touch a bill (added to the existing tenant-isolation suite). Reports are checked against hand-worked figures. The control check is tested with a deliberately broken allocation.

## 12. Build order inside phase 1

Each step ships and is tested on its own.

- **1a. Model and posting engine.** Party ledger link, voucher types, bills, allocations, entry kind, GST ledgers, the posting functions, and their tests. No screens yet.
- **1b. Voucher entry.** The API and the purchase and sales form.
- **1c. Settlement.** Bank lines against bills, the matcher, and the review panel.
- **1d. Reports.** Outstanding, party statement, control check; the invoice CSV import.
- **1e. Tally openings and linking.** Party-ledger links and bill-wise openings.

## 13. After phase 1 (not part of this note)

2. Invoice reading with a self-proof (taxable plus tax equals total, GSTIN checksum).
3. Matching and the missing-document list.
4. Connect `gst/` to the books so input tax is checked against the ledger and 2B.
5. Asset register and depreciation.
6. Payroll, TDS challans, credit cards.
7. One close screen: every control account, every open item, sign-off gated on them.

## 14. Decisions needed, in order of how much they block

1. **Party = its own ledger (A), or control ledger plus sub-ledger (B).** Recommended: A.
2. **A party that is both supplier and customer.** Recommended: one ledger, net balance.
3. **TDS timing.** Recommended: at booking by default, typed by the CA in phase 1. Needs the firm's practice.
4. **GST ledgers and the CGST/SGST/IGST split.** Recommended: add the standard set; the CA enters the split in phase 1.
5. **Settlements always need a person's confirmation in phase 1.** Recommended: yes, relaxed later once the matcher has a track record.
6. **Do purchase and sales vouchers need a draft stage before posting?** Recommended: no in phase 1 (a person posts directly, as in Tally, and sign-off is the check); phase 2's invoice reading adds drafts, since a machine's reading must be reviewed.
