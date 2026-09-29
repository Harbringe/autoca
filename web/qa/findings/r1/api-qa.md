# API QA — round r1

Covered as **admin, senior, staff, reader**, over HTTP against `http://127.0.0.1:8000`, using
two fresh synthetic clients I created myself (`QA API TestCo`, `QA API TestCo Two`, both prefixed
`QA API `) plus read-only authorisation probes against the seeded `QA Sharma Traders` and
`QA Patel & Sons`. Walked the full statement lifecycle end to end on `QA API TestCo`: upload,
opening balance, chart-of-accounts build, review queue, placement (incl. the bank's-own-ledger
refusal), approval (explicit ids and `band=HIGH`), correction, removal, `books/request` →
`books/return` → `books/request` → `books/sign-off` → locked-entry checks (`correct`, `remove`,
statement `delete`, all correctly 409 `entry_locked`) → `books/reopen` → correct-while-open →
`books/request` → `books/sign-off` again, ending signed off as instructed. Checked trial balance,
P&L, balance sheet, bank reconciliation and Tally export against the figures I built the statement
with (`node qa/tools/make-statement.mjs`), and cross-client/cross-role authorisation using the
second client. Also exercised GST registration + one run (create, reconcile, register/portal/
decisions method-gating, export, sign-off gating), file-upload validation (empty, non-PDF,
truncated, 30 MB oversized), jobs, `/me`, `/firm`, audit, the flat `/transactions/` and
`/journal-entries/` endpoints, CSRF, and a mass-assignment probe on ledger PATCH.

**Not covered**, for lack of time or of reproducible preconditions: ledger `accept`/`merge`/
`reject` (no model-proposed ledgers appeared in this session — the seeded chart already covered
everything the model suggested); GST `register`/`portal` file upload and `reconcile` match itself
(need a purchase register + GSTR-2B file, out of scope for the time available); `rules/{id}` PATCH/
DELETE; `parties/{id}` merge; `team/invites`, `team/events`, `team/members/{id}/work` in depth;
concurrent double-submission races (only sequential double-calls, per brief's "a few requests, not
a loop"). No login-lockout, TOTP-lockout, or invite-token brute-force testing was attempted —
deferred to security-auditor phase 2 per the dispatch note, since the lockout counters are shared
across all testers at 127.0.0.1.

`session.serverErrors()` was checked after every script. Two calls came back `>=500` (both the
same endpoint, see API-101).

## Findings

### API-101 · blocker · security · Job event stream 500s
- **Role / area:** staff (also reproduced as any role that can read the job), `GET /api/v1/jobs/{id}/events/`
- **Repro:** Upload a statement (`POST /api/v1/clients/{id}/statements/upload/`), take the returned
  job id (already `SUCCEEDED` — work runs inline), then `GET /api/v1/jobs/{id}/events/`.
- **Expected:** Per `openapi.yaml`, a `200` SSE stream that, since the job is already terminal,
  "will usually emit one message and close."
- **Actual:** `500`, body `A server error occurred.  Please contact the administrator.` (plain
  text, no `code`/`detail` envelope). Reproduced twice, both with a genuinely `SUCCEEDED` job I
  owned.
- **Evidence:** `web/qa/private/r1-api-12-misc.mjs` — output: `events status 500 body: A server
  error occurred.  Please contact the administrator.` and `staff.serverErrors()` returning
  `[{role:'staff', method:'GET', path:'/api/v1/jobs/<id>/events/', status:500}]`.
- **Suggested direction:** Since jobs run inline today, the SSE handler is probably choking on a
  job that is already terminal when the stream opens (e.g. trying to open a channel/queue
  subscription that no longer exists, or a serializer issue in the "emit one final message and
  close" path) — worth checking that code path specifically, and adding the `{code, detail}`
  envelope even to this failure so it isn't a bare Django 500 page.
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** api/views/core.py, api/tests/test_api.py
- **Change:** Confirmed cause: the stream body is produced after the middleware's transaction closes, so RLS had no firm context. Each poll in the generator now runs inside firm_context(firm_id) and releases it before sleeping.
- **Verify:** GET /api/v1/jobs/{id}/events/ returns 200 text/event-stream with one data: message.

### API-102 · major · GST registration validation uses 409 instead of 400
- **Role / area:** staff, `POST /api/v1/clients/{id}/gst/registrations/`
- **Repro:** `POST` with `{"gstin": "TOO-SHORT"}`, or any syntactically-15-char but checksum-invalid
  GSTIN (tried several, e.g. `00000000000000A`, `29AABCU9603R1ZM`, `27ABCDE1234F1Z0` with a
  correctly-computed check digit — all rejected; a genuine sample GSTIN `27AAPFU0939F1ZV` was
  accepted, so the validator itself works).
- **Expected:** `openapi.yaml`'s own stated convention: *"`422` means the document could not be
  read; `409` means the request conflicts with the current state; `403` is a role boundary."* A
  malformed/invalid GSTIN in the request body is plain input validation, the same category as an
  unrecognised ledger name or a non-integer `opening_balance_paise` — both of which this API
  correctly answers with `400 {"code":"invalid", ...}`.
- **Actual:** `409 {"code":"gst_rule","detail":"TOO-SHORT is not a valid GSTIN."}` — every time,
  for a field-format problem that has nothing to do with server state.
- **Evidence:** `web/qa/private/r1-api-10-gst.mjs` and the ad-hoc checksum probe:
  `bad gstin 409 {"code":"gst_rule","detail":"TOO-SHORT is not a valid GSTIN."}`; contrast with
  `duplicate ledger 400 {"code":"invalid",...}` and
  `opening balance bad type 400 {"code":"invalid","detail":"Some fields are invalid.","fields":{"opening_balance_paise":["A valid integer is required."]}}`
  from the same session.
- **Suggested direction:** Move GSTIN format/checksum validation into the serializer's `400
  invalid` path (field error on `gstin`), and reserve `409 gst_rule` for genuine state conflicts
  (e.g. "already registered for this client", which correctly stays 409).
- **Owner:** backend-dev
- **Status:** open

### API-103 · minor · Contract mismatch: GST registrations list is not paginated
- **Role / area:** staff, `GET /api/v1/clients/{id}/gst/registrations/`
- **Repro:** `GET /api/v1/clients/{client_id}/gst/registrations/` after registering one GSTIN.
- **Expected:** `openapi.yaml` documents the response as `PaginatedRegistrationList`:
  `{count, next, previous, results}` (same shape as every other list endpoint in the API).
- **Actual:** A bare JSON array: `[{"id":"...","gstin":"27AAPFU0939F1ZV","state_code":"27","registration_type":"regular"}]`.
  The shared helper's `session.all()` (which every other list endpoint in this API works with)
  throws `TypeError: r.body.results is not iterable` against this endpoint, because there is no
  `results` key.
- **Evidence:** `web/qa/private/r1-api-10-gst.mjs` run log, and the direct probe:
  `200 [{"id":"aa9e8aca-...","gstin":"27AAPFU0939F1ZV",...}]` — no `count`/`next`/`previous`.
- **Suggested direction:** Either wrap it in the standard pagination envelope (simplest, keeps the
  contract uniform — a client with many GSTINs will otherwise silently only get "whatever the
  default page size is" with no way to page further) or fix `openapi.yaml` to declare it as a
  plain array if unpaginated is intentional. Either is fine; the current mismatch is the problem.
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** api/views/gst.py, api/tests/test_gst_api.py
- **Change:** Registrations list uses DefaultPagination and returns count/next/previous/results.
- **Verify:** GET clients/{id}/gst/registrations/ has the envelope.
- **CONTRACT CHANGE:** clients_gst_registrations_list now returns the paginated envelope (matches the existing openapi.yaml; the generated types already expect it).

### API-104 · minor · Approve-rows error message is wrong when neither field is sent
- **Role / area:** staff, `POST /api/v1/clients/{id}/approvals/`
- **Repro:** `POST {}` (or any body missing both `classifications` and `band`, e.g. from a client
  that got the field name wrong).
- **Expected:** A message that distinguishes "you sent neither" from "you sent both" — the current
  wording only makes sense for the latter.
- **Actual:** `400 {"code":"invalid","detail":"Some fields are invalid.","fields":{"non_field_errors":["Send either a list of classifications or a band, and not both."]}}`
  — identical wording whether zero or two of the mutually-exclusive fields were sent.
- **Evidence:** `web/qa/private/r1-api-05b-approve-msg.mjs`: `empty body approve 400
  {"code":"invalid",... "Send either a list of classifications or a band, and not both."}`.
- **Suggested direction:** Two messages ("send one of X or Y" vs "send only one of X or Y, not
  both"), or at minimum reword to cover both cases, e.g. "Send exactly one of `classifications` or
  `band`."
- **Owner:** backend-dev
- **Status:** fixed
- **Files:** api/serializers/classify.py, api/tests/test_api.py
- **Change:** Message is now: Send exactly one of classifications or band. (both cases).
- **Verify:** POST approvals/ with {} or with both fields.
- **CONTRACT CHANGE:** the 400 message text for POST clients/{id}/approvals/ only.

## Coverage table

| Operation | Role(s) tried | Cases | Result |
|---|---|---|---|
| `POST /clients/` | admin | create QA API TestCo, QA API TestCo Two | PASS (201) |
| `GET /clients/{id}/` | admin, senior, staff, reader | own/assigned 200; unassigned 404; QA Patel & Sons 404 for senior/staff/reader | PASS |
| `PUT team/clients/{id}/lead/` | admin | set senior as lead | PASS |
| `POST team/clients/{id}/team/` | admin | assign staff | PASS |
| `GET team/members/` | admin | list, ids for later calls | PASS |
| `POST clients/{id}/statements/upload/` | staff, reader | 202+Job, `needs_opening_confirmation`, duplicate upload (`rows_already_present`==count, `is_new:false`), reader 403 | PASS |
| upload: empty file / non-PDF / truncated / 30 MB oversized | staff | all refused with readable `{code,detail}`, no 500 | PASS |
| `POST bank-accounts/{id}/opening-balance/` | staff | missing `opening_as_of` 400; set; re-set (idempotent 200); wrong type 400 | PASS |
| `GET statements/{id}/transactions/` | staff | 20 rows, `*_display` vs `*_paise` all consistent | PASS |
| `POST clients/{id}/ledgers/` | staff | create 8 ledgers; duplicate name (case-insensitive) → 400 with readable detail | PASS |
| `GET review-queue/`, `review-queue/summary/`, `review-queue/suggest/` | staff | counts consistent, `suggest` 202+Job | PASS |
| `POST classifications/{id}/review/` | staff | place all rows; refuse placement into bank's own ledger (400, readable) | PASS |
| `POST clients/{id}/approvals/` | staff | explicit `classifications`, `band=HIGH`, empty body, both-fields body, re-approve nothing-left (idempotent 201 `[]`) | PASS except API-104 (message wording) |
| `GET journal-entries/`, `/{id}/`, `/changes/` | staff, reader | all 20 entries balance Dr=Cr; `POST journal-entries/` (collection) → 405; reader `correct` → 403 | PASS |
| `POST journal-entries/{id}/correct/` | staff | missing `treatment` → 400; in-place edit pre-sign-off (`action:EDITED`, id unchanged); post-sign-off → 409 `entry_locked`; after reopen → 201 | PASS |
| `POST journal-entries/{id}/remove/` | staff | pre-sign-off 204, row returns to queue; post-sign-off → 409 `entry_locked` | PASS |
| `DELETE clients/{id}/statements/{id}/` | staff | post-sign-off → 409 `entry_locked`, readable detail | PASS |
| `GET/POST clients/{id}/books/*` (request, return, sign-off, reopen) | staff, senior | full state machine: `books_not_ready`, staff 403 on return/sign-off, senior return-with-note, re-request, sign-off, reopen (note required, 400 without), correct-while-reopened, re-sign-off | PASS |
| `GET reports/trial-balance`, `/profit-and-loss`, `/balance-sheet` | staff, reader | `balances:true`, `suspense_paise:0`, P&L `net_profit_paise` == BS `net_profit_paise` (1,60,778.98... see below), reader with no assignment → 404 | PASS |
| `GET bank-accounts/{id}/reconciliation/` | staff | `matches:true`, `difference_paise:0`, ledger closing == statement closing (₹2,50,778.98, matches the PDF I generated) | PASS |
| `GET statements/{id}/tally-export/` | staff | 20 vouchers == 20 live entries; unique `REMOTEID`s; every voucher has a `NARRATION` and a `DATE`; amounts 2-decimal; exported twice → identical length/content | PASS |
| voucher numbering after sign-off | — | Payment 1–13, Receipt 1–6, Contra 1 — all contiguous, no gaps | PASS |
| `POST gst/registrations/` | staff | bad format/checksum → see API-102; valid GSTIN → 201; duplicate → 409 | PARTIAL (API-102, API-103) |
| `POST gst/runs/` | staff | bad period pattern → 400; create → 201 | PASS |
| `POST gst/runs/{id}/reconcile/`, GET `register`/`portal`/`decisions` (wrong method) | staff | 409 `gst_rule` before register uploaded; 405 on GET for POST-only endpoints (correct per contract) | PASS |
| `GET gst/runs/{id}/export/` | staff | 200, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | PASS |
| `POST gst/runs/{id}/sign-off/` | staff, senior | staff → 403; senior → 409 `gst_rule` (reconcile first) — role gate correct, not fully exercised past that gate | PARTIAL (not built out: register/portal upload) |
| `GET /jobs/`, `/jobs/{id}/` | staff, reader | list, retrieve; reader on staff's job id → 404 (correctly scoped) | PASS |
| `GET /jobs/{id}/events/` | staff | see API-101 | **FAIL** |
| `GET /me/` | staff | 200, correct shape | PASS |
| `GET /firm/`, `/firm/owner/` | staff | 403 `permission_denied` (correct — firm.manage is not a staff permission) | PASS |
| `GET /audit/` | staff, reader | staff 403 (no `audit.view`); reader 403 | PASS |
| `GET /transactions/`, `/transactions/{id}/` | staff, senior, reader | scoped correctly to each role's assigned clients; reader denied a transaction from an unassigned client (404); no unfiltered/unscoped leak once re-tested carefully | PASS |
| Cross-client IDOR | staff | fetch client A's ledger id via client B's URL path → 404 | PASS |
| Mass assignment | staff | `PATCH ledgers/{id}` with `client: <other client>` in body → silently ignored (ledger stayed under original client) | PASS |
| CSRF | — | `POST` without `X-CSRFToken` → 403 `CSRF Failed: CSRF token missing.` | PASS |
| Cookies | — | `sessionid`: `HttpOnly; SameSite=Lax`; `csrftoken`: `SameSite=Lax`. No `Secure` flag, but tested over plain `http://127.0.0.1` locally so this isn't conclusive either way — worth a look at the deployed cookie headers by whoever can passively check Render. | not conclusive locally |
| Security headers | — | CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, COOP/CORP all present on a plain `GET` | PASS |
| Ledger accept/merge/reject | — | no model-proposed ledgers arose in this session (seeded chart already covered everything two statements' worth of transactions needed) | not exercised |
| GST register/portal upload, reconcile match | staff | needs real purchase-register/GSTR-2B files | not exercised |
| `rules/{id}`, `parties/{id}` PATCH/merge | — | — | not exercised |
| `team/invites`, `team/events`, `team/members/{id}/work` | — | — | not exercised |
| Login lockout, TOTP lockout, invite-token brute force | — | — | deferred to security-auditor phase 2 (shared 127.0.0.1 lockout counters) |

## What worked well

The statement → review → approval → sign-off → reports → Tally export pipeline is solid end to
end: every figure I checked tied out exactly to the statement I generated (trial balance
Dr==Cr, P&L `net_profit_paise` == balance sheet `net_profit_paise`, balance sheet `balances:true`
with `suspense_paise:0`, bank reconciliation `matches:true` and `difference_paise:0` against the
PDF's own closing balance, voucher numbers contiguous per FY and type after sign-off). The
sign-off lock is genuinely enforced (`409 entry_locked` on correct/remove/delete-statement, in
every case with a message that tells the reader what to do next), and `reopen` correctly requires
a note and lifts the lock cleanly. Role boundaries were consistently correct everywhere except the
one GST wrinkle above: 403 never leaked as a 404 or vice versa, cross-client access was refused at
every path I tried, and a mass-assignment attempt on a ledger's `client` field was silently
ignored rather than honoured. File-upload validation (empty, non-PDF, truncated, oversized) was
clean and readable in every case, with no 500s and no stack traces. CSRF is enforced and the
session cookie is `HttpOnly`.

As a senior CA, I would sign off `QA API TestCo`'s April 2025 books as they stand: they balance,
tie to the bank statement, and the voucher trail is intact and gapless. The one thing that would
stop me signing off *anything* in production right now is API-101 — a broken job-status stream is
a "does the flow still finish" failure mode the brief specifically asks about, and while the
underlying work does finish (jobs run inline), a client polling `/events/` on a slow statement
would see a bare 500 instead of the promised terminal message.
