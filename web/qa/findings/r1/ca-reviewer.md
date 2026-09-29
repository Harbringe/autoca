# r1 CA reviewer findings (resumed run, 2026-09-29)

Covered: as admin, senior, staff and reader on my own clients (QA CA Ashok Enterprises: April and May 2026, signed off through 31-05-2026; QA CA Bindal Traders: April 2026 uploaded, posted, opening confirmed, sent for review and signed off through 30-04-2026, March 2026 backfilled; QA CA FY Probe Jan: empty). Screens: clients, upload, Statements, Review (post all, ticked, create ledger), Day Book (entry, unpost), Reports (Trial Balance, P&L, Balance Sheet, Bank Reconciliation), Books & sign-off, Masters (ledgers, parties), Tally XML, palette and shortcuts, role buttons on every tab, FY switch, 390px. Figures compared with the API and with make-statement.mjs truth: statement opening, debits, credits and closing tied to the paisa; Trial Balance, P&L and Balance Sheet on screen equal the API; the bank ledger closing equals the statement closing once the opening is confirmed; reconciliation shows 0.00; Day Book counts equal the API's live entries (15, 20, 40); voucher numbers run gap-free and in date order after sign-off (Ashok Payment 1-26, Receipt 1-12, Contra 1-2; Bindal Payment 1-13, Receipt 1-6, Contra 1). Not covered: Print output, GST reconciliation and team screens (none exist in the web app, CA-016), rules tab, real statements. Extra data left behind: Bindal has 20 unposted March 2026 rows and is "Awaiting sign-off" after a test resend; a client "QA CA FY Probe Jan".

## Carry-over results
- M1-008 (Esc in New client loses typed name): VERIFIED 2026-09-29. Esc now shows "Discard what you have typed?" and Keep editing keeps the name.
- M1-011 (Enter right after typing in the palette opens the wrong client): VERIFIED. `dark` switched the theme, `zzzq` and `all` opened no client, whether I waited 0 or 0.6 s before Enter.
- M1-012 (Tab escapes the discard prompt): REOPENED (partly fixed), minor. Tab goes Keep editing, Discard, then onto the Close (x) button behind the prompt (the name field is locked now). Enter on that Close only dismisses the prompt and the typed name is kept, so nothing is lost. Esc on the prompt means keep editing, name kept.
- M2-009 (404 on /changes/ after Unpost): VERIFIED. Unposted an entry on Bindal with network logging: 204 on remove, no request to the removed entry's changes, no console error.
- M2-010 (checklist step 6 says "Senior CA signs off" on a client with no senior): VERIFIED. Bindal and the new client read "A firm administrator signs off (no senior CA assigned)". A related leftover is CA-011.

## Findings
### CA-001 · blocker · Day Book / Tally, narrations drafted by the assistant carry a code instead of the payee
- **Role / area:** admin, QA CA Bindal Traders, Review then Day Book
- **Repro:** upload the Bindal April 2026 statement (assistant suggests ledgers); post the rows; read the Day Book narrations (or the journal-entries API). I unposted the courier entry and posted it again to check: same result.
- **Expected:** narration names the payee as on the statement, e.g. "paid to BLUE DART EXPRESS".
- **Actual:** 6 of the 20 vouchers carry a code where the party's name should be: "Being payment made to P269D28A4 by UPI" (all four ZEPTO MARKETPLACE payments, 02/05/14/22-04-2026), "Being courier charges paid to P80974CB4 for AWB by NEFT" (BLUE DART EXPRESS, 24-04-2026), "Being amount received by cheque from P6A8B6B4A" (MEHTA HARDWARE, 27-04-2026). Those codes are in the books, the ledger and the Tally XML, and a client or auditor cannot tell who was paid. On QA CA Ashok the same payees read correctly (rows I placed by hand), so it is tied to rows the assistant drafted.
- **Evidence:** journal-entries API narrations on client 8b70e7ab-e10d-40ac-818c-9cdf9112db03; Day Book screenshot web/qa/screenshots/r1-ca-entry-dialog.png; statement rows read "NEFT DR-UTIB0000789-BLUE DART EXPRESS-AWB".
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** classify/llm.py, classify/pseudonymise.py, classify/tests/test_llm.py
- **Change:** The model's narration, rationale and question have their pseudonym tokens turned back into the payee names locally before storing; a narration that still holds an unresolved token or placeholder is dropped so the template narration is used.
- **Also (review):** the token pattern is case-insensitive, but a P/V followed only by digits (a cheque or reference number such as P20240915) is left alone rather than treated as an unresolved token; a token we sent is always looked up first. Tests: test_a_reference_number_that_looks_like_a_token_is_left_alone, test_a_lowercase_token_the_model_hands_back_is_still_caught.
- **Verify:** Re-run a statement through the model tier: stored book_narration, the Day Book and the Tally XML name the payee, never a P/V code. Rows already stored with a code are not rewritten (D7).

### CA-002 · major · Review, "Post all high-confidence" confirmation says the wrong thing
- **Role / area:** admin, Review
- **Repro:** Bindal Review with 12 "High" rows that each say "Suggested by a language model"; click "Post all high-confidence (12)".
- **Expected:** the prompt tells me who placed them and what I am about to post (count and total Dr/Cr, since I cannot undo after sign-off).
- **Actual:** "These were placed by the client's rules with high confidence." They were placed by a language model on a brand-new client that has no learned rules. No amounts or totals in the prompt. While it runs, the title flips to "Post 0 high-confidence rows?" A CA who reads "rules" will trust them more than they deserve. (Related to SCA-001; this is the wording/consent side.)
- **Evidence:** web/qa/screenshots/r1-ca-postall-confirm.png, r1-ca-postall-done.png
- **Owner:** frontend-dev
- **Status:** open

### CA-003 · minor · Review, "Create ledger" defaults to a group that is wrong for a debtor
- **Role / area:** admin, Review, inline New ledger
- **Repro:** Bindal, select MEHTA HARDWARE (receipt, assistant suggests Sundry Debtors), type a new ledger name, choose "Create ledger".
- **Expected:** the group starts at what the assistant/row suggests (Sundry Debtors) or is left unset so I must choose.
- **Actual:** the group dropdown starts at "Indirect Incomes"; pressing Enter straight away creates a customer ledger under Indirect Incomes (my own earlier scripted run left "QA CA Mehta Hardware" there, and it shows in Ashok's Trial Balance as Indirect Incomes ₹31,200). Choosing the group works.
- **Evidence:** web/qa/screenshots/r1-ca-create-ledger-dialog.png
- **Owner:** frontend-dev
- **Status:** open

### CA-004 · major · Reports and Bank Reconciliation, unconfirmed opening balance is not named as the cause
- **Role / area:** admin, QA CA Bindal Traders (one statement, opening ₹2,00,000.00 not yet confirmed), Reports
- **Repro:** upload the statement, post every row, do NOT confirm the opening balance, open Reports. Then confirm it and look again.
- **Expected:** a report that shows a bank ledger ₹2,00,000 short of the statement says why, and Bank Reconciliation points to "Confirm opening balance".
- **Actual:** the Trial Balance and Balance Sheet show the bank at ₹1,50,778.98 (statement closing is ₹3,50,778.98) and still tick "Grand Total" balanced; Bank Reconciliation says "does not reconcile at 30-04-2026 ... the difference is -₹2,00,000.00 ... Everything up to that date is approved, so this is a real break." Nothing mentions the opening balance. After I confirmed the opening (Statements tab, "Confirm opening") every figure tied: TB bank closing ₹3,50,778.98 Dr, reconciliation difference ₹0.00. A junior would go hunting for a missing ₹2 lakh. Also "everything is approved" is untrue: these are posted, not signed off.
- **Evidence:** web/qa/screenshots/r1-ca-bankrec-admin.png (after), r1-ca-bindal-open-dialog.png; API balance-sheet and trial-balance agree with the screen in both states.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/reports/ReportsScreen.tsx
- **Change:** When a bank account has no confirmed opening balance the amber banner (all report tabs, even if every row is posted) and Bank Reconciliation say 'Opening balance not confirmed' and link to Statements > Confirm opening; in Bank Reconciliation the API's 'real break' explanation is replaced by that warning while the account is unconfirmed. NOT FIXED: the API wording 'Everything up to that date is approved, so this is a real break' (GET /api/v1/bank-accounts/{id}/reconciliation/?as_of=, field `explanation`, from ledger/reconciliation.py BalanceCheck.explain) still says 'approved' for 'posted' when the opening is confirmed.
- **Verify:** Bindal Traders before confirming the opening: Reports show the amber banner naming the unconfirmed opening with a link; Bank Reconciliation leads with the same warning. After confirming, the warning disappears.
- **Backend (R1-24b):** Files: ledger/reconciliation.py, ledger/tests/test_reconciliation.py, api/tests/test_api.py. Change: BalanceCheck.explain says "posted" not "approved", and when everything is posted but the bank account's opening balance is unconfirmed it names that as the likeliest cause instead of "a real break". Verify: GET bank-accounts/{id}/reconciliation/?as_of=... `explanation`. No contract shape change (wording only). NOT CHANGED: the upper-case INCOMPLETE line in ledger/reports.py footer caption is still used by the plain-text trial balance render and the verify_statement command, and by the API caption, so it stays; the web app ignores it.

### CA-005 · minor · Bank Reconciliation, difference shown as a bare minus and books balance without Dr/Cr
- **Role / area:** admin, Reports > Bank Reconciliation (Bindal, opening not yet confirmed)
- **Repro:** open Bank Reconciliation when the books and the statement differ.
- **Expected:** figures carry Dr/Cr, and the difference is stated as an amount with its direction.
- **Actual:** "Difference -₹2,00,000.00" (bare minus) and "Balance as per books ₹1,50,778.98" with no Dr/Cr. (The Balance Sheet prints debit balances in liabilities as "(-) ₹11,420.00"; that is Tally's own habit, so I do not count it.)
- **Evidence:** web/qa/screenshots/r1-ca-bankrec-admin.png (state after confirming); API figures agree with the screen.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/reports/ReportsScreen.tsx
- **Change:** Bank Reconciliation shows books and statement balances as '₹x Dr/Cr' and the difference as an amount with words ('books are lower than the statement').
- **Verify:** Bank Reconciliation with a mismatch: Balance as per books '₹1,50,778.98 Dr', Difference '₹2,00,000.00' with 'books are lower than the statement'.

### CA-006 · minor · Trial Balance, Grand Total covers closing columns only
- **Role / area:** admin, Reports > Trial Balance
- **Repro:** Ashok (or Bindal) Trial Balance; add the Debit and Credit columns.
- **Expected:** the Grand Total row also totals the period Debit and Credit columns (Tally does).
- **Actual:** Ashok's period Debit column adds to ₹9,42,578.04 = Credit column, but the total row shows only the two closing totals (₹7,47,068.00 each). Zero cells are grey "₹0.00" in Debit/Credit but blank in Closing Dr/Cr and Opening: inconsistent.
- **Evidence:** web/qa/screenshots/r1-ca-t-admin-clients_CID_reports.png
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/reports/ReportsScreen.tsx
- **Change:** TB Grand Total row now totals Opening, Debit, Credit, Closing Dr and Closing Cr; zero cells in Debit/Credit are blank like the others.
- **Verify:** Ashok/Bindal Trial Balance: the Debit and Credit totals equal each other (e.g. ₹9,42,578.04) and the closing totals stay.

### CA-007 · minor · Opening balance dialog, no Dr/Cr choice
- **Role / area:** admin, Statements > Confirm opening
- **Repro:** Bindal Statements, "Confirm opening".
- **Expected:** a way to enter an overdrawn (Cr) opening balance; the amount shown with lakh grouping.
- **Actual:** only a rupee box, no Dr/Cr choice; prefilled as plain "200000" (no grouping or paise). The date 01-04-2026 is right.
- **Evidence:** web/qa/screenshots/r1-ca-bindal-open-dialog.png
- **Owner:** frontend-dev
- **Status:** open

### CA-008 · blocker · Statements, opening balance can be changed by staff after the books are signed off
- **Role / area:** staff (senior not tested), QA CA Ashok Enterprises, Statements > "Change opening"
- **Repro:** Ashok is signed off through 31-05-2026 (Overview says "Entries up to that date are locked"). Sign in as staff, Statements, "Change opening" on the bank account, enter 130000, "Confirm opening balance".
- **Expected:** refused, or at least a warning that it alters signed-off books, and only the lead/admin may do it (the API's own rule for locked entries is lead or admin only).
- **Actual:** accepted at once ("Opening balance confirmed"); the Trial Balance bank closing moved from ₹4,26,557.96 to ₹4,31,557.96 (statement closing is ₹4,26,557.96) and the "Difference in opening balances" moved with it. No prompt, no lock. The signed-off figures are silently different from what the senior signed. I put it back to 1,25,000 afterwards (closing ₹4,26,557.96 again).
- **Evidence:** web/qa/screenshots/r1-ca-chg-open-dialog.png; journey qa/journeys/ca-r1-chg-open.mjs; Trial Balance API before/after.
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** banking/ingest.py, api/views/banking.py (help text), banking/tests/test_continuity.py, api/tests/test_api.py
- **Change:** confirm_opening_balance refuses with 409 entry_locked when the client is signed off on or after the opening date (new or existing); confirming the figure already on file is not refused.
- **Verify:** Sign off through 30-04, then POST bank-accounts/{id}/opening-balance/ with a different figure: 409 entry_locked naming the sign-off date and who can reopen. Before sign-off it works as before.
- **CONTRACT CHANGE:** POST bank-accounts/{id}/opening-balance/ can now answer 409 entry_locked (existing error shape).

### CA-009 · major · Tally XML, no opening balance; unsigned file not marked draft
- **Role / area:** admin, Statements > "Tally XML" (Bindal)
- **Repro:** download the April Tally XML for Bindal before and after sign-off; read the vouchers.
- **Expected:** a file that reproduces the bank's balance in Tally, and a draft warning before sign-off.
- **Actual:** (1) no OPENINGBALANCE anywhere in the file (0 matches for "opening") though the account has a confirmed ₹2,00,000.00 opening, so a fresh Tally company would show the bank ₹2,00,000 short. (2) Before sign-off VOUCHERNUMBER ran against the calendar (Payment 13 on 02-04-2026, 9 on 05-04, 1 on 28-04) and neither the Books screen nor the button says these are working numbers. After sign-off the same file is right (Payment 1 on 02-04 to 13 on 28-04, Receipt 1-6, Contra 1). (3) Only one file per statement; no year or client export. Narrations in the file carry the codes from CA-001.
- **Evidence:** qa/samples/ca-r1-tally.xml (before) and a re-download after sign-off; journey ca-r1-tallyxml.mjs
- **Owner:** backend-dev
- **Status:** open

### CA-010 · major · Books & sign-off, the sign-off prompt does not say what it will lock
- **Role / area:** admin (no senior on the client), Bindal, Books & sign-off > "Sign off the books"
- **Repro:** post 20 rows (3 of them "Assistant posted"), send for review, press "Sign off the books".
- **Expected:** the prompt names the date it will sign off through, the number of vouchers and total Dr/Cr it will lock, and how many assistant-posted entries nobody has looked at (the brief: irreversible actions state counts and totals).
- **Actual:** the prompt has an empty "Sign off through" box ("Leave empty to sign off through the latest entry") and no figures. The page behind it said "Entries posted by rules that nobody has checked: 3". I signed off with the box empty; the books locked through 30-04-2026 and that counter went 3 to 0, so signing off silently marks the assistant's entries as checked. Numbering did close up correctly (Payment 1-13, Receipt 1-6, Contra 1, no gap, in date order). (Related to SCA-001/SCA-002; this is the consent side.)
- **Evidence:** web/qa/screenshots/r1-ca-signoff-dialog.png, r1-ca-bindal-signed.png
- **Owner:** frontend-dev
- **Status:** open

### CA-011 · minor · Books & sign-off and Overview, status wording contradicts itself after sign-off
- **Role / area:** admin, Bindal and Ashok
- **Repro:** sign off, then read the header, Overview and Books screens.
- **Expected:** a signed-off client reads as signed off; nothing to "send".
- **Actual:** the header chip says "Working draft" beside "Signed off through 30-04-2026"; Books says "Not yet sent for review" with a live "Send for review" button and Overview step 5 "Ready to send" (also shown on a brand-new client with no statement at all). Pressing it on a signed-off client with nothing new flips the client to "Awaiting sign-off". On a client with no senior the toast reads "Sent to the senior CA" and the history line "Sent to the senior CA"; a locked post says "Ask a senior to reopen the books".
- **Evidence:** web/qa/screenshots/r1-ca-bindal-signed.png, r1-ca-resend-after-signoff.png, r1-ca-after-send.png
- **Owner:** frontend-dev
- **Status:** open

### CA-012 · minor · New client, any date accepted as "Financial year starts"
- **Role / area:** admin, Clients > New client
- **Repro:** name "QA CA FY Probe Jan", Financial year starts 01-01-2026, Add client.
- **Expected:** Indian FY only (1 April), or the field not offered.
- **Actual:** created with "Financial year starts 01-01-2026" shown in the client list and details, but every report and the year selector still run April to March (FY 2026-27, 01-04-2026 to 31-03-2027). The field promises something the books do not do.
- **Evidence:** client faff5c57-d670-4488-bf7e-1371952b8c92 (left in place, prefixed QA CA), reports empty state text
- **Owner:** backend-dev
- **Status:** open

### CA-013 · minor · Reports at 390px wide, the whole page scrolls sideways
- **Role / area:** admin, Reports > Trial Balance at 390px
- **Repro:** narrow to 390px, open Reports.
- **Expected:** the table scrolls inside its card; the page stays 390 wide.
- **Actual:** the page itself is 760px wide (scrollWidth 760 vs 390); header and tabs sit on the left with a blank right side. Review, Day Book, Overview and Books stay within 390.
- **Evidence:** web/qa/screenshots/r1-ca-m390-reports.png
- **Owner:** frontend-dev
- **Status:** open

### CA-014 · minor · Upload, a statement that falls inside signed-off books is accepted without warning
- **Role / area:** admin, Bindal (signed off through 30-04-2026), upload March 2026 statement
- **Repro:** upload the March statement (closing ₹2,00,000.00 = the confirmed opening).
- **Expected:** told up front that 01-03-2026 to 31-03-2026 is inside signed-off books and rows cannot be posted unless the books are reopened.
- **Actual:** "Imported 20 transactions ... 20 placed in a ledger ... waiting for you to check and post"; the Review queue shows 20 rows and "Post all high-confidence (20)". Only when posting does a clear message appear ("Transaction on 31-03-2026 falls inside books signed off through 30-04-2026 ... Ask a senior to reopen the books"). The refusal is right; the wait is the problem. Bindal is left with those 20 rows unposted.
- **Evidence:** web/qa/screenshots/r1-ca-locked-post.png
- **Owner:** frontend-dev
- **Status:** open

### CA-015 · minor · Review, the assistant places payments in the group name, not in a party ledger
- **Role / area:** admin, Bindal Review
- **Repro:** read the ledger suggested for ZEPTO MARKETPLACE and MEHTA HARDWARE.
- **Expected:** a named party ledger (or a prompt to create one), as a Tally user would keep.
- **Actual:** the ledgers are literally "Sundry Creditors" and "Sundry Debtors" (the group names). All four Zepto payments (₹6,416.50) land in one ledger called Sundry Creditors, and the Balance Sheet shows it as a liability with a debit balance. The mismatched-group ledger names would also be re-created as ledgers in Tally by the export (both appear in the XML as LEDGER "Sundry Creditors" under parent Sundry Creditors).
- **Evidence:** web/qa/screenshots/r1-ca-create-ledger-dialog.png; Trial Balance rows for Bindal.
- **Owner:** backend-dev
- **Status:** open

### CA-016 · major (scope note) · GST reconciliation and team/assignments have no screen in the web app
- **Role / area:** admin, senior; whole app
- **Repro:** sign in as admin; look in the sidebar (only "Clients"), the client tabs (Overview, Statements, Review, Day Book, Reports, Books & sign-off, Masters), Ctrl+K and the `?` list.
- **Expected:** the brief's scope names GST reconciliation, Tally export and team/assignments; a CA would expect somewhere to add members, assign a senior CA or staff to a client, and run GST reconciliation.
- **Actual:** none of the three has a page or command. The API has /gst/runs and /team/members, and clients show a lead ("Senior CA: Sanjay Senior"), but no screen changes who leads or is assigned. Tally export exists only as one XML file per statement (see CA-009). If these are meant to come later, treat this as a scope note, not a defect.
- **Evidence:** web/qa/screenshots/r1-ca-palette-admin.png, r1-ca-avatar-menu.png (avatar menu holds only theme, rows density, shortcuts, sign out; the "QA Associates" footer is not a link). The senior reviewer also reached GST only over the API.
- **Owner:** user (decide if in scope)
- **Status:** open

## What worked well
- Every figure I compared (statement totals, Trial Balance, P&L, Balance Sheet, bank ledger against statement, reconciliation, Day Book counts) matched the API and the statement, with correct lakh grouping, DD-MM-YYYY dates and Dr/Cr on the Trial Balance opening.
- Sign-off renumbering: gap-free per type, in date order, with locked entries refusing posts and giving a plain reason.
- Role buttons: reader sees nothing editable on any tab; staff sees no Sign off/Reopen; senior list and client visibility followed assignments.
- Post-all and post-ticked prompts, unpost prompt ("what happens") and the FY-mismatch banners on Day Book and Overview.
- GSTIN checksum error is plain, DD-MM-YYYY date error on New client is plain, palette and `?` help are accurate.
