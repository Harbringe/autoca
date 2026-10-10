# Bill of Entry (imports): design

Date: 2026-10-11. Status: agreed in conversation, awaiting written-spec review. Nothing built.

This is the first slice of the "source-document bridging" work (five items, on hold since 2026-10-07). It covers items 2 and 5
together: a customs payment explained by its Bill of Entry (BoE), and an import duty paid in pieces. Items 1 (balance-sheet flips),
3 (post-sale discounts) and 4 (capital vs expense) get their own specs later.

## Intent

- **Problem:** a customs payment reaches the books as a bank row classified to some expense head. The truth (how much is duty that
  becomes landed cost, how much is IGST/cess credit) sits in the BoE. Today the duty is mis-split, the IGST credit is missed, and
  the GSTR-2B `IMPG` row says "verify against the bill of entry" with nothing to verify against.
- **Success:** every customs payment is explained by a BoE; the split is exact maths from the BoE, no AI; the 2B import row ties
  to it; a BoE with no supplier invoice, or the reverse, is an open item; partial payment shows "settled so far".
- **Decided with the user (2026-10-11):** the BoE posts when entered (accrual), not when fully paid. Manual entry first, PDF reader
  later. Foreign currency and forex gain/loss are out of scope.

## Data

### `BillKind.IMPORT_DUTY` ("Bill of Entry")

A bill on the credit side (the client owes Customs). Needs one migration that widens `BillKind` choices and the
`ck_bill_direction_matches_kind` constraint (`IMPORT_DUTY` joins `PURCHASE`/`CREDIT_NOTE` as CR).

Amounts on the existing bill columns:

| Column | Holds |
|---|---|
| `taxable_paise` | BCD + SWS (the duty that becomes landed cost) |
| `igst_paise`, `cess_paise` | the input-credit duties |
| `cgst`/`sgst`/`tds`/`round_off` | zero |
| `total_paise` | `taxable + igst + cess` (what Customs is owed) |
| `reference` | the BoE number |
| `bill_date` | the BoE date |
| `document` | the BoE PDF, protected, when there is one |

### `BillOfEntry` (one-to-one with the bill, `ledger/models.py`)

Fields a bill cannot hold: `port_code`, `boe_number`, `boe_date`, `icegate_ref_date` (null until known), `assessable_paise`,
`bcd_paise`, `sws_paise`, `igst_paise`, `cess_paise`, `bill` (OneToOne, PROTECT). Sum of bcd + sws must equal the bill's
`taxable_paise`; igst/cess equal the bill's columns (a check constraint plus a build-time check, so the two cannot drift).

New table rules (project standing rules): its own RLS migration via `ddl_tenant_context_operations()` + `rls_operations(table)`,
`db_default` on defaulted columns, a factory in `core/tests/factories.py` for the tenant-isolation gate.

### The Customs party

One supplier `Party` per client, named "Customs (<port code>)", created on first use. It never adopts a same-name party (existing
rule for auto-created parties). Its ledger is the party ledger of the bill, so settled-so-far is the ordinary party position.

### Identity

`core.identity.invoice_key(firm, "BOE:<port_code>", boe_number)`: port + number, with the date checked alongside, not a supplier
GSTIN. The same function the GST module uses, so a bill and a GSTR-2B `IMPG` row are recognised as one document.
(To verify when building: which of `boenum`/`boedt`/port code the 2B parser keeps on `Invoice`, see `gst/parsers.py` around line 139.)

## Posting (`ledger/boe.py`, new, pure maths separate from DB)

`plan_boe(landed_cost_ledger, bcd, sws, igst, cess) -> VoucherPlan` using the existing `billing` plan types:

- `Dr` landed-cost ledger (BCD + SWS)
- `Dr` Input IGST, `Dr` Input cess
- `Cr` Customs party ledger (total)

`post_boe(client, data, *, membership)` follows `billing._post`: permission and posting-rights checks, sealed-books refusal,
duplicate refusal by key, ACTIVE-ledger check, one atomic journal + bill + `BillOfEntry`. Landed-cost ledger defaults to the
client's "Purchases - Imports" (created via `standard_ledger`) and may be set to an inventory/other head.

The assessable value is **not** posted: it is the foreign supplier's invoice, booked as an ordinary purchase. This avoids double
counting and any foreign-currency work.

Correction of a posted BoE: remove and re-enter while books are unsigned (as `billing.remove_bill`/`revise`); after sign-off,
the rectification journal. A BoE with payments settled against it follows the existing "release payments" rule.

## Settlement and partial payment

No new settlement code. A bank payment to the Customs party settles the bill through `ledger/matching.py` (exact open amount) or
`ledger/settlement.py` (a person applies it, `propose` for partial and multi-bill). Open amount stays computed from
allocations, never stored. The BoE screen shows `settled so far / total`.

`payments_that_bypass_bills` and `payments_needing_an_invoice` (openitems) learn that a payment whose narration or payee matches
the Customs party is expected to land on a BoE, and surface it as "customs payment with no Bill of Entry" until one exists.

## Ties to the rest (no islands)

1. **Supplier invoice cross-check.** The BoE's `assessable_paise` is compared with import purchase invoices of the client in the
   same period. New open item `boe_without_invoice`: no purchase invoice with that assessable value. The reverse (an import
   invoice with no BoE) is not raised in this slice, because a domestic purchase is not an import and the Party model has no
   "foreign" flag to tell them apart; revisit when it has one.
2. **GSTR-2B.** `gst/books.py::load_register_from_books` currently selects only `PURCHASE`/`DEBIT_NOTE`, so a BoE stays out of
   the B2B register by default. Extend it to emit `IMPORT_DUTY` bills as `Section.IMPG` rows, and make `gst/matching.py`
   match an `IMPG` book row to the portal `IMPG` row (today `_portal_credit` treats `IMPG` as portal-only). Mismatch in IGST
   or ICEGATE timing shows as the usual amount mismatch / wrong period. ITC timing follows `icegate_ref_date` where set.
3. **Credit in the return.** IGST on the BoE enters ITC through the 2B match, not a separate figure.
4. **Documents.** A BoE PDF uploaded as a document is linked, never an island (a BoE with no document is an open item, as for
   any bill: `bills_without_a_document`).
5. **Reports.** Landed cost reaches the P&L / inventory purchase figure through its ledger; Input IGST through the existing
   duties-and-taxes ledgers.

## API and UI (sketch, detail in the plan)

- `POST /clients/{id}/bills-of-entry/` (create+post), `GET` list/detail, `DELETE` (remove rules above). Serializer exposes the
  settled-so-far figure. OpenAPI regenerated and `npm run gen:api` committed.
- Domain errors: a `BoeError` mapped exactly in `api/exceptions.py::DOMAIN_ERRORS` (422).
- UI: a "Bill of Entry" voucher form under Purchases (number, date, port, assessable value, BCD, SWS, IGST, cess, landed-cost
  ledger, optional file); list with settled-so-far; a "match payment" action reusing the existing settle dialog.

## Out of scope

- Foreign currency and forex gain/loss on the supplier payment.
- Reading a BoE from a PDF (follow-up; the form fields are the reader's target schema).
- Customs duty on services, advance authorisation / EPCG, bond-related duties.
- Items 1, 3, 4 of the bridging list.

## Testing

- Pure: `plan_boe` split and balance; settled-so-far arithmetic; key stability.
- DB (CI only; no Postgres on the PC): post, duplicate refusal, sealed-books refusal, payment in two pieces, remove, tenant
  isolation, 2B IMPG match.
- API: create, list, permission and error mapping. Web: form validation, settled-so-far display.

## Risks to check while planning

- `BillKind` is used in many `kind in (...)` filters (reports, party position, matching, GST). Each must be reviewed so a BoE is
  neither lost from the party/GST positions nor double counted in purchases.
- Whether the Party model can express "Customs" without a role change (`_post` checks `party.role`).
