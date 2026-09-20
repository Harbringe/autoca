# Plan: the model does the books the way a senior CA would

Status: proposal, 16 Sep 2026. Nothing here is built yet except where marked.

## The frame

Today the model is a fallback behind the rules: it is shown one row at a time,
a three-ledger chart, and asked "which of these?". A senior CA never works
that way. Given a client's bank statements and invoices for a month, a CA
does the *whole job* -- builds the chart if it is missing, books every line,
raises the vouchers the invoices call for, settles them against the bank,
reconciles, closes the month, and hands over a set of books plus a short list
of things only the client can answer.

The target for the app is exactly that: **the model drafts the complete
month; the CA reviews one pack and signs once.** Everything the model does
stays staging (the `ledger/` immutability line is untouched); the sign-off is
what makes it permanent. "Unrestricted" therefore means the model may create
any master and draft any voucher -- not that it may post.

## What a senior CA actually does, and what the app does in its place

Each stage: what the CA does by hand today, what the model does instead, what
already exists in the codebase, and what the CA still sees.

### 1. Onboard the client: know the business before booking a rupee

**CA:** reads the last year's books or the previous accountant's Tally, asks
what the business does, and sets the chart accordingly: a trader gets
Purchases/Sales/Freight and stock; a professional gets Professional Fees
income and no stock; a manufacturer gets Wages and Power. Sets up GST
registration, TDS applicability, opening balances, and party masters.

**Model:** from the client's name, GSTIN, the first statement, and any
invoices, infers the *nature of business* and builds a complete conventional
chart in one pass -- active, not proposed. Reads an existing Tally export
(masters XML) when the client has one and adopts those names verbatim.
Proposes opening balances from the first statement's opening figure and from
any trial balance provided.

**Exists:** `seed_client` (three ledgers), `standard_ledgers.py` (a list, never
applied), `contra_ledger_for`, the proposal accept/reject flow, Tally XML
export (one direction only).

**New:** a *client profile* (nature of business, GST type, TDS deductor
status, stock or not); chart-from-profile generation; Tally masters import;
opening balance entry. Drop the three-ledger seed once this exists -- its
docstring's argument ("a payee's meaning is a fact about a particular
client's business") is correct and is exactly why the chart must come from
the business, not from a universal list or from nothing.

**CA sees:** the proposed chart once, with the inferred business type at the
top. This is the highest-leverage review in the whole workflow -- one
correction here fixes a hundred rows downstream.

### 2. Collect the evidence

**CA:** chases the client for every bank statement, credit card statement,
purchase and sales invoice, loan schedule, payroll register, and GSTR-2B.
Knows what is missing from what the bank shows: an EMI implies a loan
schedule; a salary debit implies a payroll register; a supplier payment
implies an invoice.

**Model:** derives the *missing document list* from the statement itself and
issues it to the client (or the junior) before booking starts. Ingests
invoices (PDF/image) into structured lines: supplier, GSTIN, invoice no/date,
taxable value, CGST/SGST/IGST, HSN where present.

**Exists:** `documents/` registry (single table, hashed, provenance to line),
bank statement parsers proved against running balance, an OCR adapter slot.

**New:** invoice extraction (OCR adapter is a slot, not an implementation);
credit-card statement parsing; a "requested documents" list per client-month
with status.

**CA sees:** nothing at this stage. The request list goes to the client.

### 3. Book the bank statement, line by line, the way a CA would

**CA:** goes down the statement and, from narration + memory of the client,
writes each voucher: Payment, Receipt, or Contra, against the right ledger,
with a proper narration ("Being courier charges paid to ABC Courier vide UPI
ref 7781"). Handles the mechanical cases without thinking: interest, charges,
ATM withdrawal (Contra to Cash), cash deposit (Contra from Cash), own-account
transfers, card bill payments.

**Model:** the same, with the full chart and *full context*: the whole
statement (not one row), the client's history for that payee, exact amounts,
and the invoices from stage 2. It writes the voucher type, ledger, party,
narration, and tax flags for every line. Where an invoice matches a bank line
it books the bill-wise settlement rather than a bare expense (see stage 4).

What "full context" fixes that the current one-row design cannot:

| statement pattern | CA does | needs |
|---|---|---|
| RAJESH ELECTRICALS debit, later same-amount credit | reversal: reduce the original ledger, not "misc income" | sibling rows + exact amounts |
| RAHUL SHARMA advance, later settlement | party ledger: advance sits as an asset until settled | party accounting + history |
| LOAN EMI | split principal (loan liability) and interest (expense) | loan schedule, or a rate to estimate |
| BANK CHG + GST | split charge and input GST | a known split rule per bank |
| CHEQUE RETURN + CHG | reverse the original receipt; charge to bank charges | sibling rows |
| STAFF SALARY | salary expense; if payroll register given, split PF/ESI/TDS payable | payroll register |
| TDS GOVT / GST challan | Duties & Taxes -- against the *liability* booked earlier, not an expense | prior-period ledgers |

**Exists:** narration analysis (`classify/narration.py`, channels incl. CASH),
rules engine, single-row model call with pseudonymisation, `voucher_type_for`
(Payment/Receipt/Contra), `approve()` with a `narration=` kwarg nothing passes.

**Fixed in this branch:** the model's answers were being discarded whenever
it named a ledger the client lacked. Now routed to proposals (`llm.py`).

**New:** Cash-in-Hand seeded and `Channel.CASH` treated as a contra channel
(four separate blocks today; see `seeds.py`, `standard_ledgers.py`
PROPOSABLE_GROUPS, `narration.py` _TRANSFERABLE, `approval.py`
voucher_type_for); model call reshaped from "row -> ledger name" to
"statement -> draft vouchers", each with narration, party, and optional
split lines; a multi-line voucher draft (one bank line, several ledger
lines) -- `JournalLine` already supports it, staging does not.

**CA sees:** not these rows. Only the exceptions from stage 7.

### 4. Book the invoices and settle them against the bank

**CA:** raises a Purchase voucher per supplier invoice (Purchases Dr, Input
CGST Dr, Input SGST Dr / Supplier Cr) and a Sales voucher per sales invoice,
each with a bill reference. Then, on the bank line, books the *payment to the
party* against that bill -- not to an expense ledger. Deducts TDS at payment
where a section applies (194C/J/H/I...) and books TDS Payable. Handles
advances (paid or received) as party balances until the invoice arrives.

**Model:** the same. Matches bank lines to invoices on party + amount, less TDS,
within a date window; books settlements bill-wise; books unmatched supplier
payments as on-account against the party, not as expense; flags a payment
with no invoice as "needs invoice" rather than guessing the expense head.

**Exists:** `Vendor` with GSTIN, `rcm_default`, `tds_section`;
`Treatment` carries rcm and tds_section per row. But **Vendor is not a
ledger** -- every payment posts directly to an expense head, so there are no
creditor balances, no bill-wise outstanding, no advances. `VoucherType` has
Payment/Receipt/Contra/Journal only.

**New (this is the structural decision):** party accounting. `Vendor` becomes
(or gets) a `LedgerAccount` under Sundry Creditors/Debtors; Purchase and
Sales voucher types; bill references and allocations; TDS deduction at
payment. This is the fork raised earlier -- direct-to-expense vs. party-wise.
**Recommendation: party-wise.** A senior CA does not book supplier payments
to Purchases; the outstanding report is what the client asks for, and GST
ITC (stage 5) is impossible without the invoice side existing in the books.

**CA sees:** unmatched invoices and unmatched payments over a threshold; all
TDS deductions (a wrong section is a real liability).

### 5. Statutory: GST and TDS

**CA:** reconciles input tax claimed against GSTR-2B (supplier filed or not),
computes output liability from sales, applies RCM where the recipient pays,
prepares the 3B figures; reconciles TDS deducted against challans deposited.

**Model:** builds the purchase and sales registers from stage 4; matches to a
GSTR-2B upload on GSTIN + invoice no + taxable value; lists mismatches with
the likely cause (supplier not filed, invoice number typo, wrong period);
computes the 3B summary; matches TDS deducted to challan debits on the bank.

**Exists:** `gst/` is empty. `Vendor.gstin_hash` for blind matching.
Documents registry already anticipates GSTR-2B as a kind.

**New:** everything in `gst/`. Depends entirely on stage 4 existing.

**CA sees:** the 2B mismatch list and the 3B summary. Always -- this is
filed under the CA's name.

### 6. Month-end close

**CA:** bank reconciliation for each account; clears Suspense; books
accruals/provisions (audit fee, rent due, interest accrued), prepaid
adjustments, depreciation; splits loan EMI interest for the period; checks
the trial balance and the P&L for anything absurd.

**Model:** runs reconciliation per account; attempts to clear every Suspense
row with the month's added context; drafts the standard closing journals from
the client profile and prior year (depreciation schedule, recurring accruals);
runs sanity checks (expense ratios vs prior months, negative cash, debtor
balances growing with no receipts, an expense head that appeared this month
for the first time).

**Exists:** `ledger/reconciliation.py` (balance check per account and date),
reports (TB, P&L, BS), corrections as reversing entries.

**New:** Journal voucher drafting (type exists; no draft path); recurring
entry templates per client; the sanity-check pass.

**CA sees:** unreconciled differences, every Suspense row still open, every
closing journal (these are judgement entries by nature), sanity-check flags.

### 7. The review pack: the one thing the CA reads

This is the product. Not a queue of 60 rows sorted by confidence -- a
one-page pack per client-month:

1. **Chart changes** this month (new ledgers/parties the model created) --
   accept all, or rename to match the client's Tally.
2. **Questions for the client** the model could not answer from evidence:
   "Rs 25,000 cash deposit on 5 Sep -- sales, capital, or recovery?" "Rs 18,000
   IMPS to Rahul Sharma marked ADVANCE -- employee, contractor, or supplier?"
   These go to the client, not the CA.
3. **Judgement entries** for the CA: closing journals, capital-vs-revenue
   calls over a threshold, anything booked to Drawings, TDS sections applied.
4. **Exceptions:** unmatched invoices/payments, 2B mismatches, unreconciled
   bank differences, cheque returns, reversals detected.
5. **Sanity flags** from stage 6.
6. **Totals:** TB, P&L one-liner, GST payable/receivable, TDS payable.

Everything not in the pack was booked by the model with a confidence above the
firm's threshold and is signed off with the pack. The CA can still open any
row -- the queue stays -- but is not asked to.

**Exists:** `ReviewQueue` (flat rows by confidence), summary cards.

**New:** the pack itself; grouping by payee in the queue (one decision per
payee, which is how `learn_rule_from` already keys rules); the "needs a
document" and "question for client" states on a row (today a row is placed,
unresolved, or declined -- there is no "I know what this is but I need the
invoice").

### 8. Output and learning

**CA:** exports to Tally, files returns, remembers what the client is like.

**Model:** Tally XML for every voucher type (masters + vouchers); GST return
figures; and every CA correction in the pack becomes a rule or a client
policy ("this client's Zerodha credits are redemptions, not income").

**Exists:** Tally XML for Payment/Receipt/Contra; `learn_rule_from` on
counterparty; rules with priority and per-client scope.

**New:** masters export, Purchase/Sales/Journal in XML; client-level policies
as a first-class object the model reads (today it reads only ledgers and
vendor aliases).

## What "unrestricted" changes in the code

1. **The model's grant.** Today: one ledger name from a list, per row. Target:
   create ledgers as ACTIVE, create parties, draft any voucher type with
   multiple lines, attach narration, split amounts, mark a row as needing a
   document or a client answer. All as staging. `LLM_CONFIDENCE_CAP` (never
   HIGH, never bulk-approvable) goes away -- the pack replaces the cap as the
   control, and the sign-off is where responsibility sits.
2. **The model's view.** Today: one masked row, banded amount, no history.
   Target: the whole statement, exact amounts, the client's prior year, the
   invoices, the chart, the client profile and policies. The pseudonymisation
   module's own docstring says the banding and the single-row view are
   deliberate minimisation. Reversing that is a decision the firm makes, and
   it has a provider consequence: Groq's default terms carry no zero-retention
   commitment. Sending a client's full books there is a different risk from
   sending a masked row. Either a ZDR/in-country provider (the adapter
   boundary makes this one file), or keep pseudonymisation and accept weaker
   invoice matching. Decide before stage 3.
3. **The call shape.** From `complete_json(system, one batch of rows)` to a
   job: build chart -> draft vouchers -> match invoices -> close -> pack. Each
   step is a call with the prior steps' output as context. The batch-halving
   retry in `llm.py` goes away with a per-step token budget.
4. **The model.** `openai/gpt-oss-120b` on Groq is a reasoning model and the
   probe showed it classifies well when the plumbing lets it. For stages 4-7
   (matching, splitting, drafting closing entries) it needs a `reasoning_effort`
   setting the adapter does not expose yet. Evaluate one stronger model on
   the same golden set before committing.

## Build order

Dependencies, not preference. Each phase is usable on its own.

| # | phase | unlocks | touches |
|---|---|---|---|
| 0 | Cash-in-Hand seed + CASH as contra; payee-grouped queue; narration on approve | ATM/cash deposit stop being declines; review effort drops ~4x today | seeds, narration, approval, ReviewQueue |
| 1 | Client profile + chart-from-profile + Tally masters import | stage 1; every later stage has a real chart | core.Client, classify, tally.py |
| 2 | Statement-level model call: exact amounts, siblings, history, exact narration, multi-line drafts, "needs document / ask client" states | stage 3 fully; reversals, EMI split, charges+GST | llm.py, pseudonymise, models, serializer, queue |
| 3 | Party accounting: party ledgers, Purchase/Sales vouchers, bill refs, invoice extraction, TDS at payment | stage 4 | classify.models, ledger.models, documents, OCR adapter |
| 4 | GST module: registers, 2B match, 3B summary | stage 5 | gst/ |
| 5 | Close: Journal drafts, recurring templates, sanity checks | stage 6 | ledger |
| 6 | The review pack + client questions + policies | stage 7-8; "see it once" | api, frontend |

Phase 0 is a day and I would do it regardless. Phase 3 is the big one and is
where the party-wise decision is needed before any code. Phases 2 and 3 are
independent of each other and can proceed in parallel.

## What cannot be automated, and what the app does instead

Some entries need a fact the evidence does not contain: whether a cash
deposit is sales or capital; whether an IMPS to a person is salary, a
contractor, or a loan; whether a Rs 60,000 payment to an electricals shop is a
repair (expense) or a new fit-out (asset). A senior CA does not guess these
either -- they ask. The app's job is to ask the *client*, precisely and once,
and to keep the row open (not in Suspense, not as a guess) until the answer
arrives. That question list is part of the pack and is the only thing that
should ever be "unresolved" at month end.

## Open decisions

1. Party-wise accounting (recommended yes). Blocks phase 3.
2. Provider and data scope once the model sees full books. Blocks phase 2.
3. Whether the model's own confidence threshold for "book it silently" is
   per firm, per client, or fixed.
