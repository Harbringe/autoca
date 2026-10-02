# Round r1 board (orchestrator)

Sources read in full: devops.md (OPS-001..012), security-auditor.md (SEC-001..002, phase 1),
api-qa.md (API-101..104), senior-ca-reviewer.md (SCA-001..003), ux-critic.md (UX-001..017),
ca-reviewer.md (CA-001..016, carry-overs). Security phase 2 (active probes) is running; its
results will be added below and may change R1-11 and R1-14.

No code has been changed. Nothing goes to developers until the user approves this plan.
Severities are mine, re-rated from the finder's. Where I checked a claim in the code, it says so.

## Carry-overs from m1/m2 (re-checked by their finder, ca-reviewer)

M1-008 verified · M1-011 verified · M2-009 verified · M2-010 verified · **M1-012 reopened (minor)**:
Tab still reaches the Close (x) behind the discard prompt; nothing is lost. It is part of R1-29.

## Decisions needed from the user

| # | Question | My recommendation |
|---|---|---|
| D0 | **Now, before anything else:** switch the model tier off on Render (`LLM_BACKEND=integrations.llm.stub.StubLLMAdapter`) until R1-02, R1-37 and R1-38 land. | Yes. It costs only speed: rows the model would have suggested go to a person. |
| D8 | **Past disclosure.** `web/qa/private/` holds scripts from an earlier run that pushed a real statement through the model tier (names only seen; the files were not opened), and the cofounder tests on the shared system. With the leaks in R1-37, real person names have very likely already reached Groq under its default retention. | Your call: whether to ask Groq for deletion, and whether anyone must be told. I recommend no more real statements go through the model tier until R1-37 is verified. |
| D9 | Login lockout rule (R1-40): keep "a correct password does not reset the lockout" for the per-account key (strong against guessing, but lets anyone lock the owner out), or change the account key to a progressive delay and lock only the (address, account) pair. | Change it: a progressive delay on the account plus a hard lock on (address, account). It needs an ARCHITECTURE Rule 11 update. |
| D1 | **Assistant-posted entries at sign-off** (R1-01). Sign-off today silently locks entries the assistant posted that no person has looked at. | Keep automatic posting (narrowly gated in `ledger/approval.py:auto_post`, and undoable until sign-off). But **refuse sign-off** while AI_POSTED/AI_REVISED entries remain on or before the sign-off date (new refusal code); the reviewer clears them with the existing "mark as checked" step, which records a named person. The sign-off dialog shows the date, voucher count, Dr/Cr totals and any unchecked count. This changes behaviour and the contract. |
| D1b | (from SEC-004 and the security phase 2 design note) Should rows placed by the model alone auto-post? And may a client with no lead be signed off by any Senior CA assigned to it? | No to the first: auto-post only rule- or party-confirmed rows. For the second, fine as documented, but a new client should prompt the admin to set a lead. |
| D2 | A firm-level switch "rule matches may post automatically: on/off" | Later. D1 already puts a named human before every lock. |
| D3 | Dashboard facts only you can see: is `CACHE_URL` set on Render (R1-08); is there a Docker Command override (R1-06); the real proxy chain for `TRUSTED_PROXY_COUNT` (R1-09, one signed-in measurement in production). | Please check the first two now; the third after a small diagnostic lands. |
| D4 | Edits to protected files that deploy on the next push: `Dockerfile` (R1-06), CI (R1-07), `web/vercel.json` (R1-10). | Yes, each as a separate small change. The Vercel CSP is tested locally against a production build first. |
| D5 | GST reconciliation and team/assignment **screens** do not exist (API only), so an admin cannot assign a lead or staff from the web app (CA-016). | Plan them as the next feature round, not r1 fixes. Team assignment first: without it, a firm cannot onboard its people without a developer. |
| D6 | Error tracking and uptime accounts; check the keepalive cron and backups (R1-20). | Later, free tiers. Before the second firm. |
| D7 | **Production data**: if the cofounder's firm on the shared DB has posted entries with coded narrations (CA-001), they are permanent; the remedy is a correcting entry, not an edit. | After R1-02 is fixed, backend-dev runs a read-only count of affected posted entries per firm, and you decide. |

## Blockers

| ID | Source | Item | Owner | Decision |
|---|---|---|---|---|
| R1-01 | SCA-001, SCA-002, CA-010, CA-002 | Entries the assistant posted reach signed-off, locked books with nobody having looked at them; on a returning client a whole month posts itself and the checklist says "done". Sign-off does not check them, and signing off turns the "nobody has checked: 3" counter to 0 by locking them. The "Post all high-confidence" prompt says "placed by the client's rules" when a language model placed them, with no totals. *Checked in code:* SCA-002's `can_sign_off:false` was the answer to **staff's** request (the flag is a pure role check); the real gap is `ledger/books.py:sign_off`, which never looks at AI_POSTED/AI_REVISED. | backend-dev (refusal and contract), then frontend-dev (sign-off dialog, post-all prompt wording/totals, checklist) | **needs user (D1)**, then fix now |
| R1-02 | CA-001 | Narrations the model drafts carry pseudonym tokens ("Being payment made to P269D28A4 by UPI") instead of the payee, into the permanent books and the Tally XML. *Checked in code:* `classify/llm.py:464` stores the model's narration verbatim; nothing maps the tokens back. Fix: restore known tokens to the real names locally before storing narration/rationale/question; if any token is left unresolved, fall back to the template narration (`book_narration_for`). Add a test. Model output must never be stored with a token in it. | backend-dev | fix now |
| R1-03 | CA-008 | Staff can change a bank account's opening balance after the books are signed off; the signed-off Trial Balance changes silently. *Checked in code:* `banking/ingest.py:confirm_opening_balance` has no lock or role check. Fix: refuse (409 `entry_locked`) when the account's client is signed off on or after `as_of`; a change needs reopen by the lead/admin, like any locked entry. | backend-dev | fix now |
| R1-11 | SEC-001 (confirmed in phase 2) | GST working-paper xlsx: a supplier name or invoice number starting with `=` is stored as a live formula (`=HYPERLINK`, DDE). A GSTR-2B trade name is set by the supplier, so a third party can plant it. Neutralise every string cell (and strip control characters: R1-39) in `gst/report.py:working_paper`. | backend-dev | fix now |
| R1-37 | SEC-003 (re-rated from major) | Person names reach the model provider: only the first occurrence is replaced; UPI handles are unmasked; with no counterparty found the whole narration is sent; initials, 5+ word names and names with a digit are judged "business". The Groq choice rests on "nothing identifying is sent" (`integrations/llm/groq.py:35`), so this breaks its premise. Fix in `classify/pseudonymise.py`: replace every occurrence; mask VPAs; send no free text when no counterparty is found; person unless a business marker. Same module as R1-02: fix together. **Interim, user: set `LLM_BACKEND=integrations.llm.stub.StubLLMAdapter` on Render** (the code default; I checked `config/settings/base.py:488` and `integrations/llm/stub.py`). The model tier cannot fail the pipeline, so rows simply queue for a person. That one setting stops new leaks, new token narrations and model-only auto-posts until R1-02/R1-37/R1-38 land. | backend-dev + user | fix now; interim needs user (D0) |

## Majors

| ID | Source | Item | Owner | Order | Decision |
|---|---|---|---|---|---|
| R1-04 | SCA-002 (side-effect) | `books/sign-off/` silently ignores an unknown field (`through_date`) and signs off through the **latest entry**; a typo locks more than asked. Reject unknown fields on this endpoint (ideally on every write serializer); the dialog always sends an explicit date (R1-01). | backend-dev | B4 | fix now (CONTRACT CHANGE: 400 on unknown field) |
| R1-05 | contract text | `openapi.yaml` and `config/settings/base.py:579` say "Only POST approvals writes to the ledger; only a senior CA or firm admin may call it". Both halves are false (auto-post exists; staff post). Rewrite to match the real rule, with R1-01. | backend-dev, then `npm run gen:api` | B5 | fix now |
| R1-06 | CA-009 | Tally XML has no OPENINGBALANCE for the bank ledger, so a fresh Tally company shows the bank short. Before sign-off, voucher numbers are working numbers (not in date order) and nothing says so. Add the opening balance to the bank ledger master; mark a pre-sign-off export as a draft (the filename, plus a note on the Books/Statements screen). | backend-dev, frontend-dev (note) | B6 | fix now |
| R1-07 | API-101 | `GET /jobs/{id}/events/` returns a 500. Likely cause (unconfirmed): the stream is generated after the middleware's transaction has closed, so RLS has no firm context. No screen uses it (the app polls), so not a blocker, and not a security issue. | backend-dev | B7 | fix now (the test must consume the stream outside the request transaction) |
| R1-08 | OPS-006 | Login/MFA lockouts are per process and reset on every cold start if `CACHE_URL` is unset on Render. | user | - | needs user (D3) |
| R1-09 | OPS-012, SEC-007 (b) | `TRUSTED_PROXY_COUNT` cannot be right for both the Vercel-proxied and the direct path: the audit IP and the per-address lockout may be wrong (worst case, one shared bucket). Also, the Dockerfile has `--forwarded-allow-ips "*"`. | backend-dev (diagnostic) + user | - | needs user (D3); fix after measuring |
| R1-10 | OPS-002 | Upload holds one DB transaction and pooler connection through ingest plus sequential model calls (minutes); a retry doubles it (no idempotency key). Split the commit of the ingest from the model tier; add an idempotency key. The tenancy middleware is the most sensitive file in the repo: design note to me first, RLS suite after. | backend-dev | B10 | fix now (design first) |
| R1-12 | OPS-011 | Dockerfile hard-codes `--workers 3` x 2 threads on 512MB, overriding `WEB_CONCURRENCY`. Re-rated from blocker: it runs today; this is memory risk, not an outage. Drop `--workers` and let `WEB_CONCURRENCY` drive it. | backend-dev + user | B11 | needs user (D3/D4), then fix now |
| R1-13 | OPS-003 | `check --deploy` runs nowhere; add it to CI. | backend-dev | B12 | needs user (D4), then fix now |
| R1-14 | OPS-001 | The SPA shell on Vercel has no CSP, frame or nosniff headers. | frontend-dev (`web/vercel.json`, with my go-ahead) | F10 | needs user (D4), then fix now |
| R1-15 | API-102 | Invalid GSTIN returns 409 `gst_rule`; it should be 400 `invalid` with a field error. | backend-dev | B9 | fix now (CONTRACT CHANGE; there is no GST screen, so no frontend impact) |
| R1-21 | UX-001 | Every client opens on FY 2026-27, where it has no data. Default to the latest FY with statements or vouchers, remembered per client. | frontend-dev | F1 | fix now |
| R1-22 | UX-011, UX-002, UX-012 | Review worklist: narration cut to ~19 chars (the payee is cut); no search or sort; identical checkbox names and ~20 Tab stops; row controls named only "Edit"/"Active". **Decided: keep separate Withdrawal/Deposit columns** (they mirror the bank statement beside the screen; the CA reviewers read them without complaint). Narrow them and give narration the width. | frontend-dev | F2 | fix now |
| R1-23 | UX-004 | "Remember this for every payment from X" is ticked by default, below the fold, committed by Enter, and says "payment" on a receipt. **Decided: stays ticked by default** (the learning loop is the product's value; M2-003 was the CA's favourite fix; R1-01 now puts a named reviewer before any auto-posted entry locks). Move it under the ledger field, word it by direction and name the target ledger, and add a toast "Rule saved ... Undo". | frontend-dev | F3 | fix now |
| R1-24 | UX-007, CA-004, CA-005, CA-006 | Reports: one balance shows in three negative formats; INCOMPLETE is glued onto the footer; a green tick while provisional; an unconfirmed opening balance is not named as the cause of a bank difference (Bank Reconciliation calls it "a real break" and says "everything is approved" when it is only posted); the TB Grand Total omits the period Dr/Cr columns. Balances as `₹x Dr/Cr`; the Bank Recon difference with its direction; the INCOMPLETE sentence into the banner; "Provisional" instead of the tick; "Opening balance not confirmed" with a link. | frontend-dev (+ backend-dev if the recon wording comes from the API) | F4 | fix now |
| R1-25 | UX-009, CA-007, CA-014, OPS-009 | Upload and opening balance: a spinner with no elapsed time; two primaries in the result; an unformatted opening balance with no Dr/Cr choice (an overdraft) and no validation on blur; rows that fall inside signed-off books are only refused at posting time (say so in the upload result); no "waking the server" message on a cold start. | frontend-dev (+ backend-dev: the upload result reports rows inside locked books; confirm the opening accepts a negative) | F5 | fix now, after R1-10 |
| R1-26 | UX-003 | Sign-in hangs forever on "Signing in…" if the network fails. | frontend-dev | F6 | fix now |
| R1-18 | SEC-002 (confirmed; raised to major) | A 317 KB, 2,000-page PDF held one request for 139 s (inline extraction before any refusal). Any uploader can repeat it. Read the page count first and refuse above a ceiling (e.g. 300), in the upload serializer. **Separate from R1-10**: a few lines, wave 1. | backend-dev | B3 | fix now |
| R1-38 | SEC-004 (suspected) | The system prompt does not say narration, remark and counterparty are untrusted data, so a payer's remark could lift a model-only row into the auto-post band. Harden the prompt now; the policy half is D1b. | backend-dev | B6b | fix now |
| R1-40 | SEC-007 (a), confirmed from code | Anyone can lock a known account (the owner included) out for 15 minutes, again and again, with ten wrong guesses, because the per-account key refuses on its own and a correct password does not reset it. That is deliberate in ARCHITECTURE Rule 11, so changing it is a design decision (D9). | backend-dev | - | needs user (D9) |

## Minors

| ID | Source | Item | Owner | Decision |
|---|---|---|---|---|
| R1-16 | API-103 | GST registrations list is a bare array; the contract says paginated. Paginate it. | backend-dev | fix now |
| R1-17 | API-104 | Approvals error wording is wrong when neither field is sent. | backend-dev | fix now |
| R1-19 | SCA-003 | Reports ignores `?fy=` in the URL. | frontend-dev | fix now, with R1-21 |
| R1-27 | UX-005, CA-013 | At 390 px the review panel is unreachable after a tap and amounts are off-screen; the Reports page scrolls sideways. Re-rated from major (review is desk work). Now: tapping scrolls to the panel, and Reports scrolls only inside the table. Later: cards / bottom sheet. | frontend-dev | fix now (small part) |
| R1-28 | UX-006, UX-010, UX-016, CA-011 | Status and calls to action that contradict: a reader sees Confirm/Post; a new client offers "Send for review"; after sign-off it says "Working draft"/"Not yet sent" with a live Send (which flips the client to "Awaiting sign-off" with nothing new); the toast says "Sent to the senior CA" with no senior; the Books actions look like plain text. Backend: refuse `books/request` when nothing unsigned exists. | frontend-dev + backend-dev (refusal) | fix now |
| R1-29 | UX-013, UX-008, UX-015, M1-012 | The edges: a bare "Not Found" page; one `<title>` for every route; focus lost after closing a dialog; Tab escapes the discard prompt; reduced motion ignored; disabled buttons give no reason. | frontend-dev | fix now |
| R1-30 | UX-014 | Posting toast has no amount, voucher number or Undo. | frontend-dev | fix later |
| R1-31 | UX-017 | Statements repeats the upload action; the Tally column repeats the name; the FY select shows on the Clients list. | frontend-dev | fix later |
| R1-32 | CA-003 | Inline "Create ledger" defaults to Indirect Incomes; default it to the suggested group, or leave it empty to force a choice. | frontend-dev | fix now |
| R1-33 | CA-012 | "Financial year starts" accepts any 1st of a month, but the books always run April to March. Accept only 1 April (Indian FY), in the backend and the form. Backend-dev first reports (read-only) whether any existing client has another month. | backend-dev + frontend-dev | fix now |
| R1-34 | CA-015 | The model files payees into ledgers literally named "Sundry Creditors"/"Sundry Debtors" instead of party ledgers. Real for a Tally user, but it is a design question (party ledger creation). | backend-dev | fix later; design with the party-ledger work |
| R1-35 | OPS-004 | Celery is wired, but nothing enqueues and no worker exists. | backend-dev | fix later (a comment/guard only) |
| R1-36 | OPS-005 | No automatic migration on Render. | - | wontfix: TEAM.md rule 5 is the control; keep migrations additive |
| R1-20 | OPS-007, OPS-008 | No error tracking or uptime alerting; keepalive and backups unverified. | user | needs user (D6) |
| R1-39 | SEC-005 | Malformed GST inputs (a `mapping` that is not an object, odd GSTR-2B shapes, deep nesting) return 500; a control character in a supplier name makes the export 500. Should be 422 `gst_file_unreadable`. With R1-11. | backend-dev | fix now |
| R1-41 | security phase 2 | `requirements/*.txt` are not hash-pinned. | devops/backend-dev | fix later |
| - | OPS-010 | FRONTEND_URL is correct. | - | informational, closed |

## Proposed fix plan (after approval)

1. **Backend wave 1, blockers:** R1-02 + R1-37 + R1-38 (one module), R1-03, R1-11 + R1-39, R1-18 (page ceiling), then R1-01 backend + R1-04 + R1-05 (one contract change, one `gen:api`). Narrow tests, then the ledger/banking/classify modules.
2. **Frontend wave 1:** R1-01 UI (sign-off dialog, post-all prompt, checklist), R1-21 + R1-19, R1-22, R1-23, R1-24.
3. **Re-verify wave 1:** senior-ca-reviewer (R1-01, R1-04), ca-reviewer (R1-02, R1-03, R1-24, R1-22, R1-23), ux-critic (R1-21, R1-22).
4. **Backend wave 2:** R1-06, R1-07, R1-11, R1-15, R1-16, R1-17, R1-28 (refusal), R1-33, then R1-10 (design note first).
5. **Frontend wave 2:** R1-25, R1-26, R1-27, R1-28, R1-29, R1-32, R1-33 (form), R1-06 (draft note).
6. **Infra, after D3/D4:** R1-12 (Dockerfile), R1-13 (CI), R1-14 (vercel.json).
7. Re-verify wave 2 with the finders; devops re-reads the infra changes.

No migration is expected in any item above. R1-01 might want one if you choose to record *who* checked each entry more formally than today's marker; if a developer finds one is needed, they stop and say MIGRATION.

## Security phase 2

Read in full by the orchestrator (security-auditor.md, Phase 2 results).
- SEC-001 **confirmed**: a leading `=` in a supplier name or invoice number is stored as a live formula; a GSTR-2B trade name is set by the supplier, so a third party can plant it. R1-11 becomes **blocker**, fix now.
- SEC-002 **confirmed**: a 317 KB, 2,000-page PDF held a request for 139 s before failing. R1-18 becomes **major**, fix now (page ceiling before extraction), with R1-10.
- SEC-003 new, re-rated **blocker** by me: person names still reach the model provider (only the first occurrence is replaced; UPI handles are unmasked; with no counterparty found the whole narration is sent; initials and long names leak when LLM_SHARE_BUSINESS_NAMES defaults on). The architecture accepts Groq's retention terms *only because nothing identifying is sent*, so this breaks the premise the provider choice rests on. **R1-37**, backend-dev, wave 1 with R1-02 (same module): replace every occurrence, mask VPAs, send no free text when no counterparty is found, treat a name as a person unless it carries a business marker. Interim (user, D3): set LLM_SHARE_BUSINESS_NAMES=0 on Render now; that closes part of it, not all.
- SEC-004 new, major (suspected): the prompt does not mark narration text as untrusted, and a payer's remark could lift a model-only row into auto-post. **R1-38**, backend-dev: prompt hardening now. Added to D1: I recommend that **model-only rows never auto-post** (only rows that a rule or a confirmed party placed); they land in the queue as HIGH suggestions for one-click band approval.
- SEC-005 new, minor: malformed GST inputs and a control character in a supplier name cause a 500 (generic body). R1-39, backend-dev, fix now with R1-11.
- SEC-006: the same as R1-02 (tokens in narrations; the token is an unkeyed 32-bit hash). Merged into R1-02.
- SEC-007 new, major: anyone can lock a known account with 10 wrong guesses (a lockout that a correct password does not lift is by design); behind one shared proxy address it becomes firm-wide. Merged with R1-09 (needs the proxy measurement), needs user.
- Design note: a leadless client can be signed off by any assigned Senior CA (matches core/access.py; new clients start leadless). Add to D1 for the user.
- Dependencies: `requirements/*.txt` are not hash-pinned (minor, devops, fix later).
- Passed: CSRF (forged, stale, other user's, hostile Origin), session rotation, 38 cross-client write probes (all refused), sign-off by non-leads, mass assignment, git history.
- Local backend restarted on 2026-09-29, so the in-memory lockout counters are cleared.

## User answers (2026-09-29)

- Backend work: "I'll allow it; re-dispatch". Backend wave 1 dispatched (R1-37+R1-02+R1-38, R1-03, R1-11+R1-39, R1-18, R1-07, R1-16, R1-17). Frontend wave 1 dispatched (R1-21+R1-19, R1-22, R1-23, R1-24, R1-26).
- D0: "No, keep it on". The model tier stays on in production. So R1-37 was put first in backend wave 1, and I advise no real statements until it is verified.
- D1: the user asked for an explanation first. Pending.
- D9: the user asked for a better change. Proposal sent. Pending.
- Held until the answers: R1-01, R1-04, R1-05 (with R1-01), R1-40, and D3/D4 infra.
- D1: the user chose **B**, in their words: "use B for D1". Sign-off is refused while assistant-posted entries on or before the date are unchecked; model-only rows may still auto-post (SEC-004's residual risk stays until sign-off; R1-38 hardens the prompt). R1-01 (+ R1-04 and R1-05, same endpoint and contract text) is queued for backend-dev after wave 1, since only one pytest runs at a time.
- D9: the user asked "can we not flag the ip address instead?" Answered: yes, as an address-based lock with no account-wide lock (MFA covers distributed guessing), but only after R1-09 makes the address trustworthy. Awaiting confirmation.
- D9: the user answered "alright, we can go with some simple fix for now then". Interim (R1-40, queued for backend-dev after wave 1, with R1-01): (1) stop enforcing the address-only lockout key until R1-09 makes the address trustworthy, which removes the risk of one person locking out every user behind the shared proxy; (2) keep the per-account lock at 10 failures but shorten it from 15 to 5 minutes, so the worst an attacker can do to a known account is a 5-minute wait, with MFA still required after the password; (3) update ARCHITECTURE Rule 11 to say this is interim. The full address-based rule comes after D3 and R1-09.

## Frontend wave 1 result (2026-09-29)

Coded: R1-21+R1-19, R1-22, R1-23, R1-24, R1-26 (finding blocks UX-001/002/003/004/007/011/012, CA-004/005/006 and SCA-003 set to fixed). typecheck, lint, 62 unit tests and the build are clean. **Not looked at in a browser**: the web dev server was down during the run; I restarted it, and killed the developer's stray `vite preview` on 5199. Re-verification waits until backend wave 1 is done and the backend is restarted.

Queued for backend wave 2 (with R1-01, R1-04, R1-05, R1-40), from frontend-dev's "Also noticed":
- R1-23b: learned rules are created with `direction=ANY` (`classify/engine.py` ~318), so "Also place future receipts from X" also catches payments to X. Learn with the row's direction.
- R1-24b: the reconciliation `explanation` (`ledger/reconciliation.py` `BalanceCheck.explain`) says "Everything up to that date is approved": it should say posted. `ledger/reports.py:86` still builds an upper-case "INCOMPLETE:" footer caption the screen no longer uses.
- R1-23c: a `rule_created` flag on PlacementResult (additive contract change) to replace the frontend's before/after rules-list check for Undo.

## New work from the user (2026-09-29)

The user reported: no pages to manage the firm, team, client assignment/editing or staff work; and "almost half" of a statement goes unsuggested because there is no retry or queue.

Confirmed in code: `classify/llm.py:_suggest` returns on the first LLMError (after the Groq adapter's six rate-limit retries of up to a minute each) and abandons every remaining batch. Rows are left unresolved with no retry marker, all inside the upload request (R1-10).

The user proposed sending one line at a time. I advised against it: every request repeats the instructions, the chart and the context, so per-line calls multiply tokens and hit Groq's per-minute and per-day **token** limits sooner. Agreed instead:

| ID | Item | Owner | Decision |
|---|---|---|---|
| Q-1 | **Durable model queue.** The upload does ingest, rules and auto-post only, then returns. Every unresolved row is marked waiting for the assistant. A short endpoint processes one small batch (~10 rows) per call in its own transaction; on a rate limit the rows stay waiting with a retry-after, and a daily-limit state is reported plainly. **Driver: the open browser** (user's choice: "The open browser"): while a client is open, the app asks for the next batch every few seconds and shows progress; it pauses when nobody has it open. It replaces R1-10's model-tier half. Design note to me first; say MIGRATION if a per-row state field is needed. | backend-dev, then frontend-dev | after backend wave 2 |
| P-1 | **Team & roles** page: members, invite, change role, remove (admin). | frontend-dev | now (existing API) |
| P-2 | **Client assignment + edit**: set the lead and assigned staff; edit the name and description (FY start locked once entries exist). | frontend-dev | now |
| P-3 | **Work & performance** (user's choice: "Output + backlog"): per person per period, rows placed, entries posted, statements uploaded, rules written, books sent for review; plus what is waiting on each person now. No rankings or scores. Frontend builds from the existing `team/members/{id}/work`, `team/events` and `team/clients`; any metric the API lacks goes to backend-dev. | frontend-dev (+ backend-dev for gaps) | now |
| P-4 | **Firm settings**: name, owner, and the existing firm settings. | frontend-dev | now |

## Accepted risk (2026-09-29)

R1-40 interim: the automated security review flagged `core/views.py` for no longer enforcing the per-address login key. This is deliberate and user-approved ("alright, we can go with some simple fix for now then"). Still enforced: the per-account lock (10 failures, 5 minutes) and mandatory MFA. Gap accepted: password spraying across many accounts from one address is not slowed. Reason: until R1-09, production may see every visitor as one Vercel address, so any address-wide limit would let an attacker lock out every user. **Restore the address key as part of R1-09** (it depends on D3's measurement). It must not ship to production without this entry being known to the user.

## Pages built (2026-09-29): P-1..P-4

Routes: `/team`, `/firm`, `/work`, `/clients/$clientId/team` (with a new-client "set a lead" prompt). typecheck, lint, 78 unit tests and the build pass; screenshots are `web/qa/screenshots/r1-fe-*.png`. **No mutating flow has been run in the app** (shared DB): the testers must exercise invite, role, deactivate, revoke, lead, assign, client edit, firm rename and owner transfer on QA-prefixed data. "Remove member" is Deactivate (the API has no DELETE). `tbl.wrap` got `relative` (affects every table: check at 390 px).

Queued for backend (after wave 2), from the frontend's gaps:
- P-3a: a `books_sent_for_review` metric (BooksEvent REQUESTED by actor) in the member work totals and by_client.
- P-3b: `books_to_send` per client in `team/clients/` and in the member's `open_work`.
- P-3c: decide whether "entries posted" means `entries_approved` or a new `entries_posted` (including auto-posts).
- P-2a: `has_entries: bool` on Client (replaces an extra call).
- P-x: document the `team/*`, `firm/` and `firm/owner/` response schemas (and `TeamEvent.detail` per kind) so `gen:api` produces them instead of hand types.
- Tooling: `qa/tools/snap.mjs --width 390` cannot sign in (it waits for the hidden "Main" nav). Minor; for the orchestrator to brief whoever maintains qa/tools.

## Progress (2026-09-29, later)

- Backend waves 1 and 2 are done. Tests named by the developer: narrow wave 1, 159 passed and 1 skipped; wider suite, 873 passed, 1 skipped and 0 failed (RLS isolation and ledger included); re-run after late edits, 390 passed; `makemigrations --check`, no changes. The local backend was restarted with the new code.
- SEC-004's policy half (model-only rows auto-posting) is settled by the user's D1 = B: auto-posting stays, and sign-off needs a person to check the assistant's entries. The prompt hardening is done.
- The "INCOMPLETE:" caption stays in the API (text and printed reports use it); the screen ignores it. Closed.
- Frontend: `gen:api` plus the R1-01 UI (sign-off dialog, checklist, post-all wording) plus handling of the new errors, dispatched.
- **Q-1 queue**: the user approved the MIGRATION ("Approve the migration (Recommended)"). The orchestrator approved the narrow tenancy-middleware opt-out for the next-batch endpoint only (a failure mode is a loud RLS refusal, not a leak; the RLS suite must pass). Dispatched to backend-dev together with the team/work metric gaps. **The migration has not been run anywhere.** The local server uses the shared DB, so it must be applied there before local re-verification: ask the user for the go-ahead first.
- Re-verification by the testers is held until the queue lands, so that it runs once, on the final code, with one backend restart.

## Tree state (2026-09-29 evening)

- The user committed the round's work so far as 8f76fd9 on team/r1 and pushed it to origin/team/r1. `main` is unchanged (f36063f).
- The user has uncommitted work on top: a firm reporting hierarchy (teams/migrations/0005_reporting_hierarchy.py, which **backfills `manager` on existing memberships**, plus core/models.py, teams/service.py, teams/views.py, api/views/audit.py, api/serializers/core.py, superadmin/admin.py, and several web/src team/work/masters files and a new ledgers route). The user said: "yes build on top of this".
- **Two migrations are now pending, neither applied:** the user's `teams/0005_reporting_hierarchy` (a data backfill) and the Q-1 queue migration (being written). Both need the user's go-ahead before anyone runs `migrate --database=owner` against the shared DB; the local server needs them before re-verification.
- Re-dispatched: frontend (gen:api, R1-01 UI, CA-002, rule_created, new error handling) and backend (Q-1 queue, team metric gaps, schemas, `_ALIAS_TOKEN`).

## Redesign (round r2), decided 2026-09-30

The user asked to rebuild the app on the cofounder's mockup (github.com/Harbringe/test-ca, private, Bolt/React/Tailwind on demo data) and to improve it. Decisions:
- Phase 2 modules: "Show as 'Coming soon'".
- Layout: "I want u to use mockup as base and improve on it like make it better, think like pro designer". So the mockup's module sidebar plus the top-bar client and FY picker, improved.
- Timing: "Redesign now, verify once". The testers verify r1 fixes and the redesign together at the end.

The mockup is cloned read-only in the orchestrator scratchpad and served on 127.0.0.1:5190 (the orchestrator started it; stop it when the round ends). Step 1: ux-critic writes docs/design/redesign-r2.md (design system, IA mapping to our API, page specs, build waves, backend gaps). Step 2: frontend-dev builds it in waves. Backend Q-1 is still running in parallel.

## Redesign decisions (2026-09-30)

Spec: docs/design/redesign-r2.md (ux-critic). Orchestrator decisions on its section 7:
- Fonts: approved, self-hosted `@fontsource-variable/inter` and `@fontsource-variable/fraunces` (no CDN; CSP unchanged).
- Brand: graphite/emerald/champagne, with the mockup's "CA" tile as the mark, text "AutoCA". Approved (the user asked for the mockup's look).
- Coming soon: shown, per the user's choice. The hide preference may stay.
- Dashboard: v1 ships with what exists; backend builds B1 (firm overview) after Q-1; v2 when it lands.
- **Override of the spec:** the FY picker works under All clients too. Books always run April to March, and R1-33 restricts `fy_start` to 1 April (backend validation + form); "clients can start in January" is the CA-012 bug, not a design constraint.
- User: names, "Use the new names (Recommended)", so Bank statements and Work pipeline. GST: "Build GST screens now (Recommended)", so wave 6.
- User on the fake metrics: "can we add stuff to measure them with as well?" Orchestrator definitions (backend B9, after Q-1, with B1):
  - AI automation %: rows that reached the books without a person placing them (rule/model placement, then posted) / all rows, per period.
  - Accuracy: of rule/model placements, the share posted unchanged (changed, corrected or unposted count against).
  - Time saved: an estimate, labelled: automatic rows × a firm-set minutes-per-row (default 2, in Settings).
  - Risk: a per-client "Needs attention" with reasons (unreconciled, months missing, unchecked assistant entries, unsigned too long, Suspense balance).
  - Staff efficiency % is replaced by turnaround times (upload to posted; request to sign-off) per person; no hours are recorded, and no rankings (the user's earlier choice).

## State and decisions (2026-09-30 morning)

- The user moved the work to branch `preview/r2-redesign` (commit 5076260, pushed to origin; it contains the queue, the user's reporting hierarchy and the redesign waves 1-2 code). `team/r1` stays as the r1 record. `main` untouched. Agents now work on preview/r2-redesign, uncommitted.
- Local servers are down (the session ended). **The local backend cannot run on this code until two migrations are applied to the shared DB** (classify/0015_model_queue, teams/0005_reporting_hierarchy): the models reference columns that do not exist yet. The user approved both ("Both: queue + hierarchy (Recommended)") and will run `manage.py migrate --database=owner` themselves ("You run it"). No agent and not the orchestrator runs it. Waiting for the user to say it is done; then the orchestrator restarts the servers and lets the testers and snaps run.
- **Deploy caution:** the branch's frontend calls endpoints and fields that main's backend on Render lacks, and the migrations are not on production. A Vercel preview of this branch proxies to the production backend, so it will misbehave until the backend and migrations are deployed. Do not merge to main before the migrations run on the production DB (which is the same shared DB, so running them once covers both), and before the backend code deploys.
- Hierarchy decisions by the user (all three), sent to backend-dev: "No: owner only (Recommended)" for administrators changing administrators; "Fall back to an admin (Recommended)" when a firm has no Senior CA; "Show the owner, refuse changes" for the owner's visibility. The 7 failing older tests are to be brought in line with those decisions, not the other way round. Also in that dispatch: R1-33 (FY start must be 1 April) and B1 (firm overview endpoint).
- Frontend-dev continues waves 2-4 (code-level checks only until servers return); waves 5-7 (reports, dashboard, work pipeline, staff, settings, GST screens, polish) follow after B1.
- Still to do after that: B9 metrics (automation %, accuracy, estimated time saved, per-client "needs attention", turnaround per person) and then one re-verification round by all testers.

## Progress (2026-10-01)

- Backend (hierarchy per the user's 3 answers; R1-33 FY 1 April; B1 `GET /firm/overview/`): done, wider suite passed (about 954 collected, 1 skipped, exit 0; includes RLS isolation and ledger), no new migration. Side effect noted: removing the owner masking also removed the hiding of owner actions from administrators in audit and team events; kept unless the user says otherwise.
- Frontend redesign waves 1 to 4 done (typecheck, lint, 112 tests, build clean); not seen on a screen yet.
- Dispatched: backend (GST OpenAPI schemas B5/B6, `next-batch` schema check, B9 metrics endpoint `GET /firm/metrics/`, no migration) and frontend wave 5 (gen:api, hierarchy UI, reports, All-clients landings from overview, dashboard, work pipeline, staff, settings).
- Next: wave 6 GST screens (after the GST schemas), wave 7 polish, then the user's migrations, servers back, and ONE verification round by all testers (r1 fixes + redesign). Metrics UI (automation %, accuracy, estimated time saved, needs attention, turnaround) follows B9.

## Progress (2026-10-01, later)

- Backend: GST OpenAPI schemas, `GET /firm/metrics/` (automation share, accuracy that errs high, labelled estimate of minutes saved, needs-attention reasons, turnaround per person), `next-batch` confirmed in the schema. Full suite passed, no migration. Note: the full suite takes about 25 minutes.
- Frontend: wave 5 done (pipeline, staff, settings, dashboard, reports, landings, clients list on overview). Dispatched waves 6-7 (GST screens, measured figures UI, polish/a11y/dark/390).
- Backend is idle. After the frontend reports: the user runs the two migrations; the orchestrator restarts the servers; ONE verification round by all testers (r1 fixes and the redesign), with the testers briefed on both. Bring up for the testers: the UX critic and CA reviewers must judge the new design against docs/design/redesign-r2.md.

## Build complete (2026-10-01)

Redesign waves 1-7 built on preview/r2-redesign (uncommitted): typecheck, lint, 173 tests, build all clean. **Nothing seen on a screen yet.** Not built or deviating (frontend-dev's list): client picker reuses the palette (no combobox, recents, lead rows); single-client dashboard not wired; palette "Post ready rows / Send for review" actions; FY picker stays in the top bar at 390 px; error toasts are not persistent; no focus-to-first-invalid-field on submit failure; 200%/400% zoom and keyboard-only passes not done; no statement delete or Tally XML link on the Statements tab; API gaps: B3 (PAN etc.), B4 (per-statement standing), overview has no Returned state or unconfirmed-opening flag, /audit/ not in the OpenAPI schema (hand-typed).
Testers should look first at: focus after sidebar/palette navigation; Day Book drawer and statement-rows dialog at narrow width; top bar at 390 px; dark theme (Provisional alert, offline strip, assistant chips, sidebar chips); GST run page title/focus; an unknown address inside the shell.

**Gate: the user runs `manage.py migrate --database=owner` (classify/0015_model_queue, teams/0005_reporting_hierarchy). Then the orchestrator restarts the servers and runs the single verification round** (ca-reviewer, senior-ca-reviewer, api-qa, ux-critic, security-auditor re-check, devops re-read of the infra items), each briefed with the finding ids to re-verify and the redesign spec to judge against. Pending user decisions still open: D3 (Render dashboard facts), D4 (Dockerfile/CI/vercel.json edits), D5/D6, D7, R1-09, R1-12/13/14.

## INCIDENT 2026-10-01 (production uploads failing) and new decisions

- The user ran the migrations on the shared DB. `classify/0015_model_queue` added `model_attempts` NOT NULL with no database default; production (Render) still runs the previous release, whose INSERT omits the column, so every production statement upload fails with NotNullViolation (seen in the user's Render log at 23:36 and 23:37 IST). Cause: the migration I approved as "additive/optional"; one column was not. This is the OPS-005 risk made real. Hot fix (user, SQL, instant, reversible): `ALTER TABLE classify_transaction_classification ALTER COLUMN model_attempts SET DEFAULT 0;`. Permanent: corrective migration `classify/0016` with `db_default=0`, plus a guard test and an ARCHITECTURE note (dispatched to backend-dev). TEAM.md rule 5 now says migrations must be backward-compatible with the live release.
- Same log, R1-09 evidence: `login failed ip=10.28.29.130` and `ip=10.25.98.2` are private addresses, so production's client_ip resolves to an internal hop, not the visitor. The audit IP is wrong (and the address lockout, which is already off, would have been wrong).
- A bot probed `/admin` on the backend (normal; /admin is public, behind login).
- Tally decisions by the user: import by "Upload Tally exports (Recommended)"; the old Tally export: "Remove it". The scope question (chart + opening balances, past vouchers, or everything) was not answered: asked again after the incident. Memory note: todo-import-client-ledgers-from-tally (client's own chart as the default).

## Tally import: decisions (2026-10-02)

Design note: docs/design/tally-import.md. User decisions: "Openings table (Recommended)"; "Approve defusedxml (Recommended)"; "Add the missing groups (Recommended)"; earlier "Upload Tally exports (Recommended)" and "Remove it" (the old Tally export). Phase A (chart + opening balances) is being built by backend-dev; phase B (vouchers) is outline only and needs: a real anonymised sample from a real Tally company (masters XML and Excel, Trial Balance for one FY; Tally Prime and ERP 9 if clients use it), how a company whose books began earlier supplies its FY-start opening, and which voucher types to cover. Migrations still to run by the user: classify/0016 (db default), then the Tally import migration(s) when built.
Then: frontend (import screen, preview/conflicts, removal of the export buttons and links), rewording of "must match Tally exactly" copy, QA re-verification includes the import with synthetic Tally files.
