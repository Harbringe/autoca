# Senior CA review — round r1

I took one client, **QA SCA Kapoor Textiles** (my own, prefix `QA SCA `), through the
full cycle: onboarding as admin, two consecutive months of synthetic bank statements
(April and June 2025, deliberately skipping May), opening balance confirmation, chart
of accounts, classification and rule-learning, per-row approval, correction after
return, sign-off, reopen, re-sign-off, reports (Trial Balance, P&L, Balance Sheet, Day
Book, Bank Reconciliation), voucher numbering, Tally export (twice), and a smoke test
of the GST reconciliation module. I worked as `admin` for setup, `staff` for
preparation, `senior` for review/sign-off, and `reader` briefly for the read-only
check, both over the API (`web/qa/journeys/sca-r1-*.mjs`) and on screen
(`node qa/tools/snap.mjs`, plus two Playwright journeys for FY-toggle and role
screens). Screenshots are under `web/qa/screenshots/sca-r1-*.png`.

I did **not** get to: the GSTR-2B upload/reconcile/decisions/sign-off sequence beyond
creating a registration and a draft run (the module exists and responds sensibly, but
I did not push real register/2B data through it); the year-end (31 March) crossing;
concurrent edits by two people on one row; multi-bank-account clients. All server
calls came back clean — `serverErrors()` was empty on every script.

## Findings

### SCA-001 · blocker · Statement upload posts straight to the ledger once rules exist, with no human decision
- **Role:** staff (upload), senior (books)
- **Repro:** As staff, upload April's statement for a client with no history; place and
  approve all 20 rows normally, some with `learn: true` (`api/v1/classifications/{id}/review/`
  → `api/v1/clients/{id}/approvals/`). Sign the client off through 30-04-2025. Then
  upload June's statement for the *same* bank account (`allow_gap: true`, since May is
  deliberately missing) — same recurring counterparties as April (Zepto, Sunrise
  Packaging, Orbit Retail, Lotus Distributors, salary, rent, GST payment, etc).
- **Expected:** The contract states, at the top of `openapi.yaml`: *"Nothing is final
  until a senior CA approves it. Uploading a statement and classifying its rows
  produces suggestions. Only `POST /clients/{id}/approvals/` writes to the ledger."*
  I expected June's rows to land in the review queue as HIGH-band suggestions,
  waiting for someone (staff or senior) to approve them — the same as April's first
  pass.
- **Actual:** The upload job for June returned `"auto_posted": 20, "rows_posted": 20,
  "rows_ready_to_post": 0`. The review queue was empty (`count: 0`) immediately after
  upload. All 20 June entries were already live in `journal-entries` — nobody had
  called `approvals/`, and nobody (staff or senior) had looked at a single row. The
  client's Overview checklist then showed **every step green**, including "Place
  every transaction in a ledger (done)" and "Send for review (done)", for a month
  that no human ever touched.
- **Evidence:** `web/qa/journeys/sca-r1-gap-dup.mjs` (upload output), `web/qa/journeys/sca-r1-june-check.mjs`
  (20 June entries, `queue count: 0`), `web/qa/screenshots/sca-r1-overview-after-june-signoff.png`
- **Suggested direction:** Rule-matched rows on ingest should still land in the review
  queue as suggestions (however high-confidence), not bypass `approvals/` entirely.
  If auto-posting rule matches is deliberate policy, the Overview checklist and the
  Day Book must say plainly that a month posted itself with no reviewer, not present
  it identically to a month someone actually worked through.
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** ledger/books.py, api/exceptions.py, api/views/books.py, ledger/tests/test_signoff.py, ledger/tests/test_ai_workflow.py
- **Change:** PARTIAL (user decision D1 option B): automatic posting is unchanged; instead books.sign_off is refused (409 ai_entries_unchecked, count in the message) while any entry dated on or before the sign-off date and after the previous sign-off still carries the AI_POSTED or AI_REVISED marker. The existing "mark reviewed" step clears them. The UI half (dialog, post-all wording) is frontend-dev.
- **Verify:** With auto-posted entries unchecked, POST books/sign-off/ answers 409 ai_entries_unchecked; after POST books/mark-reviewed/ it succeeds; a marker on an entry dated after the sign-off date does not block.
- **CONTRACT CHANGE:** POST clients/{id}/books/sign-off/ can answer 409 code `ai_entries_unchecked`.

### SCA-002 · blocker · Sign-off succeeds even when the books' own status says it cannot
- **Role:** senior
- **Repro:** Continuing from SCA-001: `GET clients/{id}/books/` right after the June
  upload and the staff's `books/request/` call reported `"can_sign_off": false` (20
  `ai_posted` entries pending). As senior, call `POST clients/{id}/books/sign-off/`
  with `{"through_date": "2025-06-30"}` anyway.
- **Expected:** A 403 or 409 refusing the sign-off, since the server's own status
  endpoint says it is not allowed yet (and the button a senior sees on screen would be
  built from that same flag).
- **Actual:** `200`, `"signed_off_through": "2025-06-30"`. The sign-off succeeded, and
  in the same response `ai_posted` was silently reset to `0` — the 20 never-reviewed,
  auto-posted entries are now permanently locked. `can_sign_off: false` was decorative,
  not enforced.
- **Evidence:** `web/qa/journeys/sca-r1-june-signoff-attempt.mjs` — request response
  shows `can_sign_off: false`; the very next call, sign-off, returns `200`.
- **Suggested direction:** `books/sign-off/` should re-check the same condition its own
  `GET` reports and refuse with a clear reason if unreviewed AI-posted entries remain,
  the same way it already correctly refuses a request that is too early
  (`books_not_ready`) or a locked-entry correction (`entry_locked`).
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** ledger/books.py, api/exceptions.py, api/views/books.py, config/settings/base.py (API description), api/tests/test_api.py, ledger/tests/test_signoff.py
- **Change:** Sign-off refuses unchecked assistant entries (see SCA-001) and the sign-off endpoint rejects unknown fields with 400 (a `through_date` typo no longer signs off through the latest entry). The API description now states the real rule: a person posts, or the assistant auto-posts high-confidence rows, marked and changeable until sign-off, and sign-off needs a person to have checked them. (R1-04, R1-05)
- **Verify:** POST books/sign-off/ with {"through_date": "..."}: 400, field named in `fields`; nothing is locked. Read the description at the top of /api/schema/.
- **CONTRACT CHANGE:** sign-off: 400 on an unknown field; 409 `ai_entries_unchecked`; the API description text changes (regenerate openapi.yaml).

### SCA-003 · major · A financial year picked with `?fy=` in the URL is silently ignored on Reports
- **Role:** senior
- **Repro:** `node qa/tools/snap.mjs --as senior --path "clients/{id}/reports?fy=2025"`.
  Compare against clicking the in-page "Show FY 2025-26" link on the same route.
- **Expected:** The query string drives which year's Trial Balance/P&L/Balance Sheet
  is shown, so a report can be linked or bookmarked for a specific year — the kind of
  link a senior emails to a colleague or pastes into a working-paper index.
- **Actual:** With `?fy=2025` in the URL the page still showed FY 2026-27's TB (0
  entries, only carried-forward balances). Only the in-page toggle actually changes
  the year; the URL parameter has no effect. Once toggled correctly by hand, the
  figures do tie to the API exactly (₹4,61,034.00 both sides, 20 entries) — this is a
  navigation defect, not a wrong figure.
- **Evidence:** `web/qa/screenshots/sca-r1-reports.png` (fy=2025 URL, still shows
  2026-27) vs `web/qa/screenshots/sca-r1-reports-fy25-clicked.png` (after clicking the
  in-page link, correct).
- **Suggested direction:** Have the FY selector read from and write to the URL, as the
  in-page link's target seems to already compute correctly.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/shell/useFy.ts, web/src/routes/_app/clients/$clientId/route.tsx, web/src/features/reports/ReportsScreen.tsx
- **Change:** ?fy=YYYY (start year) on any client route now drives the year, and the report tab links keep it.
- **Verify:** node qa/tools/snap.mjs --as senior --path "clients/{id}/reports?fy=2025" shows FY 2025-26 figures directly; switching report tab keeps ?fy=2025; a junk value (?fy=abc) is ignored.

## Figures that tied (would not have signed if any of these were off)

- Statement parse for April: opening ₹1,50,000.00, closing ₹3,00,778.98, total
  debit ₹1,60,255.02, total credit ₹3,11,034.00, 20 rows — all exact against the
  generator's own printed truth.
- Trial Balance, both via API and on screen (once the correct FY was selected):
  total debit = total credit = ₹4,61,034.00, `balances: true`.
- P&L net profit (₹1,72,198.98) = Balance Sheet net profit; Balance Sheet
  `total_assets_paise` = `total_liabilities_and_profit_paise`; `suspense_paise: 0`.
- Bank reconciliation at 30-04-2025: books ₹3,00,778.98, statement ₹3,00,778.98,
  difference ₹0.00, `matches: true`.
- Day Book: 20 vouchers, debit total ₹1,60,255.02 / credit total ₹3,11,034.00 —
  matches the statement's own totals exactly.
- Voucher numbering after sign-off: Payment 1–13, Receipt 1–6, Contra 1 — no gaps.
- Tally export: well-formed XML (parsed with Python's `xml.dom.minidom`),
  `voucher_count: 20` twice, all 20 `REMOTEID`s identical and stable across two
  exports, every voucher carries a narration.

## What worked well

- The ATM cash withdrawal on the April statement was posted as a **Contra**
  (bank → cash), not a Payment, without me touching it — correct Tally treatment,
  and it's one of the easiest things for a tool to get wrong.
- Bank charges and bank interest on the statement's own last lines were also
  auto-posted correctly and immediately, with proper narrations ("Being ₹17.70 paid
  ... towards Bank Charges", "Being interest of Rs 684.00 credited by bank for
  period..."). These three (contra, charges, interest) were the only rows auto-posted
  on the *first* statement, which is the right amount of automation for a client with
  no history yet — it's the second statement (SCA-001) where it goes too far.
- Placing a row in the bank's own ledger is refused with a plain-English reason
  ("This is the bank account the transaction came from. Choose the other side of the
  entry."), not a generic validation error.
- A statement that doesn't continue from the last one on file is refused by default
  (`statement_period_missing`), with the option to acknowledge the gap deliberately
  (`allow_gap`) — exactly the missing-period handling a CA needs, and the message is
  one I could read aloud to a client.
- GSTIN checksum validation is real (rejected a made-up GSTIN, accepted one with a
  correctly computed check digit).
- Re-uploading the same statement is idempotent: `rows_already_present` equal to the
  row count, no duplicate rows, no double posting.
- The review/return/sign-off/reopen/re-sign-off cycle (before I hit SCA-001/002) was
  clean: staff attempting sign-off or return got a clear 403; a locked entry's
  correction or a signed statement's deletion got a clear 409 `entry_locked` with the
  date and who can lift it; the history log on `books/` records every action with
  actor, timestamp and note, and the client-side "Books & sign-off" screen renders it
  as a legible audit trail a client's auditor would accept.
- A correction before sign-off edits the entry in place (voucher number unchanged,
  full before/after in `changes/`); the same correction after a reopen creates a new
  linked reversing entry instead — the system remembers an entry once touched sign-off
  and treats it more carefully from then on, which is the right instinct.
- Amounts are lakh-grouped with two decimals throughout, dates are DD-MM-YYYY, Dr/Cr
  suffixes are used rather than a bare minus sign, and Tally's own words (Ledger,
  Voucher, Narration, Duties & Taxes, Contra) are used correctly on screen.
- Role separation held everywhere I checked: `reader` (unassigned to this client) saw
  only the one client they're actually on; `QA Patel & Sons` was a clean 404 for
  senior and staff; staff never saw a sign-off or return control.

## Would I sign it?

**Not yet.** SCA-001 and SCA-002 are the reason. A firm's ordinary month is exactly
the case that broke here: a returning client whose vendors, salary run and rent are
the same as last month. On the second month I touched, the software posted an entire
month's books to the immutable ledger without one person — staff or senior — looking
at a single row, presented that month's checklist as fully done, and then let me sign
off over its own "not ready" flag. I would not put my name to a Balance Sheet where
I cannot show, from the system's own record, that anyone reviewed what went into it.
Everything downstream of that — the Trial Balance, the reconciliation, the Tally
export — was numerically correct in my test, which is exactly what makes this
dangerous: the figures tie, so nothing would catch it in a review, only the absence
of a review itself. Fix SCA-001 (or make the automatic posting honestly labelled and
optional) and SCA-002 (enforce what the status endpoint already promises), and I
would sign the rest of what I saw without hesitation — the accounting itself, where a
human was actually in the loop, was better than most of the practice tools I've used.

## What I would still need (ranked)

1. **A hard stop between "the model is sure" and "the ledger changed."** Even with
   SCA-001/002 fixed, I would want a firm-level setting for whether rule-matched rows
   may auto-post at all, or whether they always land in the queue for a one-click
   band approval — the latter costs a reviewer thirty seconds and buys an audit trail
   with a named human on it. Every one of my clients would be affected by this.
2. **TDS.** The `tds_section` field exists on a treatment and a party, but I did not
   see anywhere the system computes or reminds me of a threshold crossing (e.g. rent
   crossing ₹2,40,000 in a year, a contractor payment crossing ₹30,000 single/₹1,00,000
   aggregate). Most of my clients need this every month; today I'd keep a separate
   TDS working file regardless of what this tool produces.
3. **GST filing support beyond reconciliation.** The reconciliation module (register,
   GSTR-2B match, decisions, sign-off, export) is genuinely built and the GSTR-3B
   shape looked right in my brief smoke test, but I did not get to prove the match
   logic against real mismatches this round. Worth a dedicated pass next round.
4. **A visible "who reviewed this row" trail on the Day Book / Review screens**, not
   just in the `books/` history. Right now "Assistant posted" is the only on-screen
   marker I saw distinguishing a rule/AI posting from a human one, and (per SCA-001)
   it can end up locked into signed-off books with nobody having cleared it.
5. **Multi-year comparison and a client portal / document-request flow** — I didn't
   test these this round because they weren't in scope, but they're routine practice
   needs I'd keep another tool for today.
