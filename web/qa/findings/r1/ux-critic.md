# UX critic, round r1

**Summary.** Covered on the local app, mostly as admin with reader spot checks (staff and senior views share the same screens): sign-in, clients list, new client, a client's Overview, Statements, upload dialog (including the ~9 s processing state and result), opening-balance dialog, Review queue and decision panel (keyboard, post, offline, bulk-post confirm), Day Book, Reports (TB, P&L, BS, Bank Recon, print), Books & sign-off, Masters (Ledgers, Parties, Rules), avatar menu, palette and shortcuts sheet, dark theme, 390 px touch, 320 px reflow, reduced motion, offline, 404s. Contrast was measured (computed colours with opacity blending) on 8 screens in both themes: the only failures are disabled buttons. I created one client, QA UX Test Traders, and uploaded one synthetic statement to it; no seeded client was changed (one Sharma row was viewed only). Not reached: MFA screens with a second factor, GST reconciliation and team/assignment screens (there is no entry point for either in the navigation or the avatar menu, so I treated them as unbuilt), slow-network throttling beyond the natural 9 s upload, 1920 px beyond the existing overview screenshot. Findings already reported by others (SCA-001..003, API-101..103) are not repeated; UX-004 adds the interaction angle to SCA-001.

## Findings

### UX-001 · major · Financial-year default lands every tab on an empty year
- **Role / area:** all roles, every client tab (Overview, Review, Day Book, Reports, Books)
- **Repro:** sign in, open QA Sharma Traders (statements are April 2025, FY 2025-26). Today is Sep 2026 so the top-bar FY defaults to FY 2026-27.
- **Expected:** a client opens on the year that holds their data (or the last year with activity).
- **Actual:** Day Book says "Nothing posted in FY 2026-27" (0 vouchers), Reports shows a Trial Balance "0 entries" with only opening balances. A banner ("You are looking at FY 2026-27, but this client's statements are in FY 2025-26") appears on every tab, with a "Show FY 2025-26" button that must be pressed again per client. The first impression of every client is "empty / broken".
- **Evidence:** web/qa/screenshots/r1-ux-daybook-admin.png, r1-ux-reports-admin.png
- **Suggested direction:** default the FY to the latest FY with statements/vouchers for that client (fall back to current FY only for a client with no data), and remember the choice per client. Keep the banner only when the user has deliberately picked an empty year. Where it stays, make it a quiet one-line note, not a full-width blue bar above every table.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/lib/fy.ts, web/src/features/shell/useFy.ts, web/src/features/shell/Shell.tsx, web/src/features/clients/Workspace.tsx, web/src/lib/preferences.tsx, web/src/routes/_app/clients/$clientId/route.tsx, web/src/features/daybook/DayBookScreen.tsx, web/src/features/reports/ReportsScreen.tsx
- **Change:** A client opens on its latest year with statements or vouchers (current FY only if it has none); an explicit pick is remembered per client and written to ?fy=; the mismatch banner is now a one-line muted note shown only when the picked year is empty; the FY select shows only inside a client.
- **Verify:** Open QA Sharma Traders (statements April 2025) on any tab: it opens on FY 2025-26 with no banner. Pick FY 2026-27 in the top bar: the URL gains ?fy=2026, a one-line note offers 'Show FY 2025-26', and returning to the client later keeps your pick. A client with no data opens on the current FY.

### UX-002 · major · Every review-row checkbox has the same accessible name and is its own Tab stop
- **Role / area:** all, /clients/:id/review
- **Repro:** Tab through the page with a screen reader or read the ariaSnapshot: 16 checkboxes all named "Tick for posting". Getting from the table to the decision panel takes ~20 Tabs (checkboxes 20-36 then the panel).
- **Expected:** name includes the row ("Select 26-04-2025 ₹61,800.00 NEFT CR-ICIC..."); the table is one Tab stop (roving tabindex), arrows/j/k move, Space ticks.
- **Actual:** unnamed-in-context checkboxes; long Tab run. (j/k/arrow row movement itself works and is good; keep it.)
- **Evidence:** ux-r1-a11y.mjs output
- **Suggested direction:** aria-label={`Select ${date} ${amount} ${narration}`}; make the checkbox column tabindex=-1 except the active row, and add `x` to tick the active row (Gmail convention) and show it in the shortcuts sheet.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/review/ReviewScreen.tsx
- **Change:** Each row checkbox is named 'Select <date> <amount> <payee or narration>'; the table is one Tab stop (roving tabindex on the selected row, checkboxes tabindex -1); Space on a row ticks it; the existing x shortcut (listed in the ? sheet as 'Tick the current row for posting') is now guarded to rows that can be ticked; focus follows j/k/arrows when it is inside the table.
- **Verify:** Tab from the search box: one stop lands on the selected row, the next Tab leaves the table. ariaSnapshot shows distinct checkbox names. j/k/arrows move, x or Space ticks, ? lists 'Tick the current row for posting'.

### UX-003 · major · Sign-in hangs on "Signing in…" when the network fails
- **Role / area:** any, sign-in page (`/`)
- **Repro:** open the sign-in page, go offline (Playwright `setOffline(true)`), enter email and password, press Sign in, wait 12 s.
- **Expected:** within a few seconds an inline message ("Could not reach the server. Check your connection and try again"), button re-enabled, focus in the password field.
- **Actual:** button stays "Signing in…" and disabled, no message, nothing to retry. (Inside the app the same failure is handled well: red toast "Could not reach the server. Check your connection and try again.")
- **Evidence:** web/qa/journeys/ux-r1-signin.mjs, screenshot r1-ux-signin-offline.png
- **Suggested direction:** reuse the in-app network-error path for the sign-in mutation; show it as an inline `role=alert` under the form (not a toast that vanishes) and add a ~15 s client-side timeout.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/auth/LoginScreen.tsx, web/src/api/client.ts, web/src/session/session.tsx
- **Change:** The sign-in mutation ran in TanStack's default 'online' network mode, which parks it while the browser is offline (the cause of the endless 'Signing in…'); it now uses networkMode 'always', a 15 s AbortController timeout, shows the inline role=alert message, and puts focus in the password field.
- **Verify:** Offline (Playwright setOffline) enter email and password, Sign in: within a moment the message 'Could not reach the server. Check your connection and try again.' appears under the form, the button says 'Sign in' again and the password field has focus. A wrong password also returns focus to the password field.

### UX-004 · major · Review "Place in ledger" teaches a rule by default, hidden below the fold
- **Role / area:** admin/senior/staff, /clients/:id/review, "Needs a ledger" decision panel
- **Repro:** open a client with an unplaced row (QA UX Test Traders, row "MEHTA HARDWARE"), pick any ledger.
- **Expected:** an action that changes how future statements are posted is visible, opt-in or clearly announced, and worded for the row in front of you.
- **Actual:** a checkbox at the bottom of the panel is ticked by default: "Remember this for every payment from MEHTA HARDWARE" (the row is a receipt, the wording says payment). Enter (the advertised fast path) commits it. With SCA-001 (learned rules auto-post next time) this is a silent, cumulative side effect of the routine key.
- **Evidence:** web/qa/screenshots/r1-ux-offline-confirm.png
- **Suggested direction:** move it directly under the ledger field and state its reach ("Also place future receipts from MEHTA HARDWARE in Bank Interest Received"); default unticked for low-confidence rows. After placing, toast "Rule saved: MEHTA HARDWARE to Sales. Undo" (10 s).
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/review/ReviewScreen.tsx
- **Change:** The remember-this checkbox (still ticked by default, per the board) now sits directly under the ledger field and reads 'Also place future receipts from X in <chosen ledger>' or 'payments to X' by direction; after placing with it ticked the toast says 'Rule saved: X to Sales' with an Undo (10 s) that deletes the rule, offered only when this decision created it, placed/revised/posted nothing else, and the person may edit rules (staff without that permission see the toast without Undo).
- **Verify:** Review > Needs a ledger, select MEHTA HARDWARE (a receipt): the checkbox is under the ledger field and the wording follows the ledger you pick. Place with it ticked: toast 'Placed in ... Rule saved: ...' with Undo; Undo removes the rule (Masters > Rules) and rows already placed stay. If the payee already had a rule (updated, not created) the toast has no Undo, because the API does not say new vs updated.
- **Backend (R1-23b, R1-23c):** Files: classify/engine.py (learn_rule_from direction; rules_for tie-break so a directional rule outranks an older either-direction one for the same payee), api/serializers/classify.py, api/views/classify.py, classify/tests/test_engine.py, api/tests/test_api.py. Change: a rule learned from a decision now takes the row's direction (DEBIT or CREDIT) instead of ANY, so "future receipts from X" does not catch payments to X (existing rules untouched); the review response has `rule_created` (bool). Verify: POST classifications/{id}/review/ with learn true on a receipt: `rule_created` true, and the rule's direction is CREDIT. **CONTRACT CHANGE (additive):** PlacementResult.rule_created.

### UX-005 · major · On a phone the review decision panel is unreachable and amounts are off-screen
- **Role / area:** all, /clients/:id/review at 390 px
- **Repro:** 390x800 touch, open Review with 16 rows; tap a row.
- **Expected:** the tap opens the decision; amounts visible.
- **Actual:** the row is only highlighted. The "Post entry" button is at y=1730 of a 1799 px page, after the whole list; nothing scrolls to it. The table scroller is 702 px wide inside 356 px with no scroll hint, so Withdrawal, Deposit and Ledger are hidden (only Date and a 16-character narration show).
- **Evidence:** r1-ux-m-review.png, r1-ux-m-review-tap.png, journeys/ux-r1-mobile2.mjs
- **Suggested direction:** below 768 px render each row as a two-line card (date left, amount right in tabular figures on line 1; narration wrapped to 2 lines and ledger chip on line 2) and open the decision panel as a bottom sheet (85 vh) with Post pinned in its footer.
- **Owner:** frontend-dev
- **Status:** open

### UX-006 · minor · Read-only users are offered actions that dead-end
- **Role / area:** reader, /clients/:id (Overview)
- **Repro:** sign in as qa.reader, open QA Sharma Traders.
- **Expected:** no call to action the role cannot perform.
- **Actual:** the checklist shows "Confirm" and "Post" buttons (they are links to Statements and Review); the step is highlighted amber "Next step". Statements then shows "Not confirmed" with no control, and Review says "Your role can look at the queue but not place rows." The only "Read only" cue is 12 px grey text at the bottom of the sidebar.
- **Evidence:** r1-ux-overview-reader.png, r1-ux-reader-review.png, r1-ux-reader-statements.png
- **Suggested direction:** hide step buttons when the role cannot act and word the step "Waiting for a Senior CA to confirm"; put a "Read only" chip beside the client name in the page header.
- **Owner:** frontend-dev
- **Status:** open

### UX-007 · major · Reports: run-on "INCOMPLETE" footer, three negative formats, a green tick on provisional books
- **Role / area:** all, /clients/:id/reports (TB, P&L, BS, Bank Recon), Sharma Traders FY 2025-26
- **Actual:** (a) footer: "QA Sharma Traders · FY 2025-26 · 4 entries · generated 29-09-2026 01:05 INCOMPLETE: 16 transaction(s) are classified but not approved and are not included in these figures." then "Generated 29-09-2026, 01:05" again at the right; raw upper-case server text is glued on with no separator. (b) The same bank balance appears as `-₹20,753.70` (Bank Recon and BS totals), `(-) ₹20,753.70` (BS asset line) and as a Closing Cr column (TB). Balance Sheet totals are negative on both sides (`-₹10,753.70`). (c) TB Grand Total carries a green tick although the books are provisional and the bank is at a credit balance only because the opening balance is unconfirmed; the amber banner mentions the 16 unposted rows, not the unconfirmed opening (Overview step 2 says reconciliation is meaningless until it is).
- **Expected:** one negative convention; a tick that can be trusted.
- **Evidence:** r1-ux-reports-fy25.png, r1-ux-rep-balance.png, r1-ux-rep-bank.png
- **Suggested direction:** balances as `₹20,753.70 Cr`/`Dr` everywhere (accountant convention), `(₹…)` only for variances; footer one line "FY 2025-26 · 4 entries · generated 29-09-2026 01:05" with the INCOMPLETE sentence moved into the amber banner in sentence case; show "Provisional" in place of the tick while the banner is up, and add "Opening balance not confirmed" with a link to the banner.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/reports/ReportsScreen.tsx, web/src/lib/format.ts, web/src/lib/format.test.ts
- **Change:** Balances read plain on their natural side and '₹x Cr'/'₹x Dr' (or Tally's '(-)' for a debit among liabilities) otherwise, totals included; footer is one line built from the report fields; the INCOMPLETE sentence is in the amber banner in sentence case; a 'Provisional' pill replaces the green tick while the banner is up; banner and Bank Reconciliation say 'Opening balance not confirmed' with a link to Statements.
- **Verify:** Reports for Sharma Traders FY 2025-26: banner reads 'Provisional. 16 transactions ... classified but not yet posted...', no ₹ '-' totals on the Balance Sheet, footer is one line, TB Grand Total row shows a Provisional pill instead of the tick.

### UX-008 · minor · Closing a dialog drops keyboard focus to the top of the page
- **Role / area:** all, Upload dialog (check others)
- **Repro:** Review tab, activate "Upload bank statement", press Esc.
- **Actual:** `document.activeElement` is BODY; the next Tab starts at the sidebar. Expected: focus returns to the button that opened it.
- **Suggested direction:** restore focus to the invoker in `onCloseAutoFocus` (the trigger is probably a controlled open state with no `Trigger`).
- **Owner:** frontend-dev
- **Status:** open

### UX-009 · major · Upload result dialog: two competing primaries, unformatted amount, no sense of progress
- **Role / area:** admin/senior/staff, upload flow, QA UX Test Traders
- **Repro:** upload a statement to a new client; watch the dialog for ~9 s, then read the result.
- **Actual:** processing is an indeterminate spinner with one line of copy, no elapsed time, no stage, no cancel or "carry on in background" (the copy says "up to a minute"; it took 9 s, but a user cannot tell 9 s from stuck). The result stacks a green success block, a 5-row summary, a grey block of three 30-word sentences ("Where the 20 rows stand now"), an amber opening-balance form with a dark primary, and a second dark primary "Review 17 rows". The opening balance field is prefilled `125000` (no lakh grouping, no decimals) though it accepts `1,25,000.50`; typing `abc` stays `abc` with no inline error on blur.
- **Expected:** one primary at a time, figures formatted like everywhere else, progress that shows life.
- **Evidence:** r1-ux-upload-progress-4.png, r1-ux-upload-after.png, r1-ux-ob-dialog.png
- **Suggested direction:** show elapsed seconds ("Reading... 12 s") and a "Keep working" button that closes the dialog and leaves a progress chip in the header. Result: three count chips (3 auto-posted, 15 to post, 2 need a ledger) instead of prose; "Confirm opening balance" is the only filled button until confirmed, "Review 17 rows" is outline. Format the amount on blur (`1,25,000.00`) and validate on blur.
- **Owner:** frontend-dev
- **Status:** open

### UX-010 · minor · New client's checklist offers "Send for review" before anything exists
- **Role / area:** admin, /clients/:id right after creating a client
- **Repro:** create QA UX Test Traders, look at Overview.
- **Actual:** step 5 reads "Send for review. Ready to send." with an enabled button while steps 1 to 4 are pending and there is nothing to send.
- **Expected:** disabled with the reason ("Nothing to send yet").
- **Evidence:** r1-ux-newclient-landing.png
- **Suggested direction:** enable only when posted vouchers exist and nothing is pending.
- **Owner:** frontend-dev
- **Status:** open

### UX-011 · major · Review table hides the one thing you decide on: narration is cut to ~19 characters
- **Role / area:** admin/senior/staff/reader, /clients/:id/review at 1440 px
- **Repro:** open Review for QA Sharma Traders (FY 2025-26 rows).
- **Expected:** the payee/narration readable in the list, so the routine pass (scan, Enter, Enter) never needs the side panel to identify a row.
- **Actual:** narration shows `NEFT CR-ICIC0000456-LOTU...`, `ACH D- MAHAVITARAN ELE...`, `UPI/501234567893/QA Shar...`: the prefix (mode, IFSC, UPI id) is exactly the part that never differs, and the payee name is what is cut. Ledger is also cut (`Electricity Cha...`, `Telephone & I...`, `Postage & Co...`) because a "Check" chip sits inside the cell. Withdrawal and Deposit are two right-aligned columns that are half empty. There is no sort, no search and no amount filter on this list (Day Book has a search box; Review does not). The word "Check" is used as a confidence chip in each row, as a filter pill in "Confidence: Any / High / Check / Decide", and as a verb in the page copy ("Check and post"): a chip that reads like a button.
- **Evidence:** web/qa/screenshots/r1-ux-review-admin.png, r1-ux-narration-hover.png
- **Suggested direction:** narration column `flex: 1` with `line-clamp-2` (or strip the first token "NEFT CR-/UPI/..." and show it as a small muted prefix chip), Amount as one signed column (`+61,800.00` green / `-48,000.00` ink, tabular, right-aligned, with Dr/Cr in the header tooltip) to give narration ~140 px more; ledger column 160 px min with the confidence shown as a 8 px dot (amber = check, red = decide, none = high) with a `title`; add a search field and clickable sort on Date and Amount above the table. Wireframe:
  ```
  [ ] 26-04  NEFT CR ICIC0000456 LOTUS DISTRIBUTORS LLP-INV 1049     +61,800.00  Sales          (amber dot)
  [ ] 19-04  NEFT CR HDFC0001234 ORBIT RETAIL PVT LTD-INV 1047       +92,250.00  Sales
  ```
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/review/ReviewScreen.tsx
- **Change:** Narration gets the width (payee on line 1, narration clamped to 1-2 lines, full text in title); Withdrawal/Deposit columns shrink to content (kept separate); confidence is an 8 px dot with title and accessible name instead of the chip; search box (narration, payee, ledger, amount as typed) and sortable Date and Amount headers with aria-sort.
- **Verify:** Review > Ready to post at 1440 px: payees and narrations are readable, ledger names are no longer cut by a chip, amber/red dots carry a tooltip; type '61800' or 'lotus' in the search box; click Date / Withdrawal headers to sort (third click clears).

### UX-012 · minor · Repeated, indistinguishable control names in tables (screen reader and voice control)
- **Role / area:** all, Masters > Ledgers (11 buttons named "Edit"), Masters > Rules (4 checkboxes named "Active"), Review (16 checkboxes named "Tick for posting", see UX-002)
- **Repro:** ariaSnapshot / `getByRole('button', {name: 'Edit'})` returns 11 matches; a voice user saying "click Edit" has no way to say which ledger.
- **Expected:** "Edit Electricity Charges", "Active: Mode is FEE, Paid or received -> Bank Charges".
- **Suggested direction:** add `aria-label` with the row's key to every row-level control; keep the visible text short.
- **Owner:** frontend-dev
- **Status:** fixed
- **Files:** web/src/features/masters/MastersScreen.tsx, web/src/features/review/ReviewScreen.tsx
- **Change:** Masters row controls are named by their row: 'Edit <ledger>', 'Edit <party>', 'Active: <match> <pattern>, <direction>, to <ledger>', 'Delete rule: ...'; Review checkboxes as UX-002.
- **Verify:** Masters > Ledgers: getByRole('button', {name: 'Edit Electricity Charges'}) matches once; Rules: each Active checkbox has a distinct name.

### UX-013 · minor · Unknown URL shows a bare "Not Found" with no app, no way back; a bad client id leaves "..." in the switcher
- **Role / area:** any, `/nope-404`, `/clients/0000...0000`
- **Actual:** a path that is not a route renders the browser-default text "Not Found" on a grey page (no header, no link to Clients). A well-formed but unknown client id shows a red "Not available" banner (good copy) but the client switcher still reads "..." and there is no "Back to clients" link. All pages have the same `<title>` "AutoCA", so browser tabs, history and screen-reader route changes are indistinguishable (WCAG 2.4.2).
- **Evidence:** r1-ux-404.png, r1-ux-badclient.png, journeys/ux-r1-del.mjs (titles)
- **Suggested direction:** a router `notFoundComponent` inside the shell with "This page does not exist. Go to Clients"; set `document.title` per route ("Review (16) - QA Sharma Traders - AutoCA") and move focus to the page H1 on route change.
- **Owner:** frontend-dev
- **Status:** open

### UX-014 · minor · Posting feedback is late and thin
- **Role / area:** admin/senior/staff, Review, key `P`
- **Repro:** select a ready row, press P, watch the screen (journeys/ux-r1-post.mjs).
- **Actual:** nothing changes for ~600 to 1000 ms (no pending state on the row or button), then the row disappears and a toast "Posted to the Day Book" shows for ~5 s with no amount, no voucher number, no Undo. A second P at 150 ms is correctly ignored (good). A user who has posted 40 rows cannot tell from the toast which one just went.
- **Suggested direction:** dim the row and show a spinner in the button at once; toast "Posted: Payment 3, ₹11,420.00 to GST Paid. Undo" (Undo unposts, 8 s), and keep the last one available under the queue heading ("Last posted: ... Undo").
- **Owner:** frontend-dev
- **Status:** open

### UX-015 · minor · Reduced-motion preference is not honoured; disabled buttons explain nothing
- **Role / area:** all
- **Actual:** with `prefers-reduced-motion: reduce` the dialog still runs its 0.15 s `enter` (fade and zoom) animation. Disabled controls (Review "Ask assistant to suggest", Books "Send for review", sign-in "Sign in" before typing) give no reason; the two coloured ones measure 3.4:1 (light) and 2.7:1 (dark), exempt as disabled but they are also the only place the reason could be read.
- **Suggested direction:** `@media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration: .01ms !important; transition-duration: .01ms !important } }` (leave the spinner, it is a progress signal); use `aria-disabled` plus a visible reason line under the button ("Nothing waiting to suggest for", "Can be sent once nothing is waiting").
- **Owner:** frontend-dev
- **Status:** open

### UX-016 · minor · Books & sign-off: the two secondary actions look like plain text
- **Role / area:** admin/senior, /clients/:id/books
- **Actual:** next to the grey disabled "Send for review" button, "Mark assistant entries as checked" and "Review or unpost them in the Day Book" are rendered as bare bold text with no border, underline or icon; they are actions (one is a bulk state change). They sit on one line with equal weight.
- **Evidence:** r1-ux-books-admin.png
- **Suggested direction:** make "Mark assistant entries as checked" an outline button (it changes 2 entries), and "Review them in the Day Book" a normal underlined link on its own line under the counts row; the row with "Entries posted by rules that nobody has checked: 2" should carry the button at its right edge.
- **Owner:** frontend-dev
- **Status:** open

### UX-017 · minor · Statements page repeats the upload action and the Tally column repeats the account
- **Role / area:** /clients/:id/statements
- **Actual:** "Upload bank statement" appears twice (header and card); the card adds no information the header button lacks. "Ledger in Tally" repeats the account name in every row, and the Masters tab says the same about names. The Financial-year select is also shown on the Clients list, where it does nothing.
- **Suggested direction:** drop the card and keep the header button; show "Ledger in Tally" only when it differs from the account name; hide the FY select outside a client.
- **Owner:** frontend-dev
- **Status:** open

## What worked well (leave alone)

- Keyboard model on Review: j/k and arrows move the row, Enter confirms, P posts, `?` opens a complete shortcuts sheet, G-then-letter navigation, Alt+C switcher. Focus rings are a solid 2 px on every stop. A double P is ignored (no double post).
- Honest states: offline inside the app gives a clear red toast; "Not saved yet: press Enter or Place in ledger" on an edited panel; destructive actions (Remove statement, Post all high-confidence) ask first with a full explanation of the consequence; empty Day Book explains itself and links onwards.
- Number display: lakh grouping, two decimals, right-aligned tabular numerals, DD-MM-YYYY throughout; TB, P&L, BS balance to the paisa on screen; print stylesheet is clean (report only, no chrome).
- Form validation on New client: inline message under the field, focus moves to it, hint text explains the April-March rule.
- Contrast: measured pass on all visible text in light and dark except disabled buttons. 320 px reflow has no page-level scroll (except Reports at 390 px, see below).
- The Overview checklist ("what is next, and why") is the best onboarding device in the product.

## The design in one page

Five changes that would raise the whole product's feel most:

1. **Open every client in the year that holds their data (UX-001).** Today every first look at a client is an empty screen plus a blue banner. Default FY per client to the latest year with statements; remember it; make the banner a quiet inline note.
2. **Make Review a proper worklist (UX-011, UX-002, UX-005).** Give narration the width, merge Withdrawal/Deposit into one signed Amount column, show confidence as a dot, add search and sort, one Tab stop with an accessible row name, and a bottom-sheet decision on phones. This is the screen used 200 times a day.
3. **One primary action per surface (UX-009, UX-007, UX-016).** The upload result dialog, the report footers and the Books page each mix equal-weight actions or glued-together text. Rule: one filled button, everything else outline or link, and statuses (tick, Provisional, Not confirmed) that never contradict the banner above them.
4. **Say what a keystroke will change (UX-004, UX-014).** Rules learned silently, toasts without an amount, no Undo. Every state-changing key should name the row, the amount and the reach, and offer Undo for 8 s.
5. **Finish the edges (UX-003, UX-013, UX-008, UX-006, UX-015).** Sign-in on a dead network, unknown URLs, per-route page titles, focus return after dialogs, role-aware calls to action, reduced motion. None is hard; together they are what makes an accountant trust the shell.

Keep: the navy sidebar plus white work area, the single amber accent, the Overview checklist, the restrained type scale, Tally vocabulary (Day Book, Vch No., Particulars, Contra), and the shortcuts culture.

Also noticed, minor: Reports at 390 px scrolls the whole page sideways (document width 640 px) instead of only the table; 22 controls are smaller than 44 px on touch.
