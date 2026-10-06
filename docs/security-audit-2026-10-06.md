# AutoCA security audit, 2026-10-06

Branch `dev`, HEAD `f134e01`. Read-only review of the code plus a few offline probes. The local `.env` database is
unreachable, so nothing was run against a database. No `.env` file was opened and no secret value appears here. Nothing
was sent to any deployed URL.

Confidence labels follow the team format, two values only. **confirmed** means I reproduced it (ran code or a Django
test client). **suspected** means I traced it in the code but could not execute it against a database, or a condition
could not be checked from here. In the table and headings, "by reading" is shorthand for "suspected (traced in code)".

An earlier round (`web/qa/findings/r1/security-auditor.md`, SEC-001 to SEC-007) already covered pseudonymisation, prompt
injection, GST formula injection, the page ceiling and login lockout. Those are not repeated unless this round found a
residual or a regression; section 4 says where each stands.

## 1. Summary, ranked

| ID | Severity | Title | Confidence |
|----|----------|-------|------------|
| A-01 | High | A staff member can change a ledger's group, name and active flag after entries are posted, including inside signed-off books | by reading |
| A-02 | Medium | Rule regex validator is bypassed by alternation, so one rule can freeze every web worker | confirmed (validator bypass, super-linear timing measured) |
| A-03 | High | Party and imported debtor, creditor and loan ledger names are sent to the model provider unmasked (prompt `history`, `related` and `ledgers`) | by reading |
| A-04 | Medium | The full OpenAPI schema and the API docs are served to anyone, without login | confirmed |
| A-05 | Medium | `/admin/login/` has no throttle or lockout and is public through Caddy | by reading |
| A-06 | Medium | The audit log is not append-only in the database, and personal-data reads are not audited | by reading |
| A-07 | Medium | GST spreadsheet upload has no unpacked-size guard; expensive endpoints have no per-user rate limit | suspected |
| A-08 | Low | Login throttle is keyed on the email only (lockout of a named account, no per-address limit) | by reading (known, interim) |
| A-09 | Low | `POST /clients/{id}/bank-accounts/` is routable and can create an empty, undecryptable account | by reading |
| A-10 | Low | Deploy script ships the branch tip, not the tested commit; CI hardening gaps; AWS side not reviewable from the repo | by reading |
| A-11 | Low | The data-encryption master key and the blind-index key sit in the web container's environment | by reading (documented) |
| A-12 | Low | Deactivating a user (`is_active=False`) does not end live sessions | by reading |
| A-13 | Low | Money fields have no upper bound, and settlement allocations have no count bound | by reading |
| A-14 | Low | Dependencies: transitive packages are unpinned; `urllib3` 2.7.0 has three advisories in the dev venv | confirmed (scanner output) |
| A-15 | Low | SECURITY DEFINER functions in `superadmin/sql.py` leave `pg_temp` first in the search path | by reading |
| A-16 | Info | Model-only rows can still auto-post (accepted decision D1 = B in round r1) | known |

Nothing found in this pass lets one firm read or write another firm's rows. The tenant wall (RLS plus the app and owner
role split) held up under every path I traced. Section 3 lists what was checked and found sound.

---

## 2. Findings

### A-01 (High) Ledger group, name and active flag can be edited after posting and after sign-off

- **Who and what.** Any member with `ledger.manage` (Staff, Senior CA, Firm admin; Staff is limited to assigned clients)
  can `PATCH /api/v1/clients/{client}/ledgers/{id}/` with `{"group": "..."}`, `{"name": "..."}` or `{"is_active": false}`
  on a ledger that already has posted journal lines, in books a Senior CA has signed off. The trial balance, profit and
  loss and balance sheet are computed live from `ledger_account__group` (`ledger/reports.py:310-345`, `:246-277`), so
  signed-off figures change with no journal entry, no change-log row and no lock. For example: move "Office Rent" from an
  expense group to an income group, or a loan ledger into a current-asset group. The books stay balanced, which makes it
  hard to notice.
- **Why it is a bypass of the stated promise.** The journal is immutable at the database; the classification that gives
  every line its meaning is not. The Tally import already knows this: it refuses a group change on a ledger with posted
  lines (`ledger/tally_import.py:356-364`, `api/views/tally.py:127`). The ledger API has no such rule.
- **Second effect, bank ledgers.** A bank account's ledger is found by name (`BankAccount.ledger_name`, see
  `classify/seeds.py:108-141`, which exists precisely because "a name changed any other way would leave the account
  pointing at an empty ledger"). `LedgerAccountSerializer` lets the same ledger be renamed through the generic endpoint,
  skipping `rename_account_ledger`. The account then points at a name that no longer exists, `contra_ledger_for` opens a
  second empty ledger, and the check `classification.ledger.name == bank_account.ledger_name` in
  `ledger/approval.py:122` stops protecting the bank side. Party ledgers (Sundry Creditors and Debtors) can be regrouped
  the same way, which changes which side of `ledger/partyreports.py:121` they are reported on.
- **Where.** `api/serializers/classify.py:45-51` (`name`, `group`, `is_active` are writable), `api/views/classify.py:83-100`
  (`ledger.manage` on PATCH and DELETE, no object rule, no lock check), `classify/models.py:121-124` (no guard). I read
  every trigger migration: the only classify triggers are on `classification` (`0010`/`0020`) and on `classify_party`
  (`0019`, same-client check on `ledger_id`), so nothing in the database guards `classify_ledger_account.group` or `name`.
- **Reproduction.** As a Staff user assigned to a client with signed-off books: `PATCH .../ledgers/<id>/` body
  `{"group":"INDIRECT_INCOME"}` (any value from `LedgerGroup`), then `GET .../reports/profit-and-loss/?fy=...`. The figures
  move although `signed_off_through` covers the year.
- **Fix direction.** Reject a change to `group` (and `name` for a bank or party ledger) when the ledger has journal lines,
  openings or allocations, and always once the books are signed off through any date it was used. Make `name` read-only for
  bank and party ledgers and route renames through the existing helpers. Back it with a trigger on `classify_ledger_account`
  that raises when `group` changes and `ledger_journal_line` rows exist (same pattern as `client_signoff_guard`), so it
  holds for code that never goes through the view. Add a change-log row (`EntryChange` style) for any allowed edit.

### A-02 (Medium) Regex rule validator is bypassed by alternation; ReDoS freezes web workers

- **Who and what.** A member with `suggestion.edit` (Staff and up) can create a regex rule that the validator accepts but
  that backtracks exponentially. The pattern is then run with `re.search` on every narration of every statement for that
  client, inline in the request thread (`classify/models.py:538`), and again on each re-categorise. `re` holds the GIL and
  has no timeout, so the gunicorn worker is frozen until its 120 s timeout kills it, and the rule is still there for the
  next upload. Workers are shared by all firms (3 workers, 2 threads, `Dockerfile:36-39`), so one firm's staff member can
  degrade the platform. A malicious or careless insider is enough; payer-controlled narration text supplies the trigger
  string (long alphanumeric references are normal in UPI and NEFT narrations).
- **Evidence (confirmed).** The guard `_NESTED_QUANTIFIER = \([^()]*[+*][^()]*\)\s*[+*{]`
  (`api/serializers/classify.py:35`) only catches a quantifier inside a quantified group. I ran it:
  `(a|aa)+$`, `(a|a)*$` and `(a?){25}a{25}` all pass the validator. `(a|aa)+$` against `"a"*N + "!"` took 0.001 s at
  N=18, 0.005 s at 22 and 0.016 s at 24, growing by about a factor of 1.6 per added character, so a 50 to 60 character
  run costs minutes to days.
- **Where.** `api/serializers/classify.py:35, 195-224`; evaluation at `classify/models.py:538`.
- **Fix direction.** Do not try to detect catastrophic patterns with a regex. Either drop `REGEX` as a user-supplied match
  type (the other match types cover the product's need), or run user patterns with a linear-time engine (`google-re2`
  bindings), or evaluate with a hard time budget in a subprocess. At minimum cap the length of the text the pattern runs
  against.

### A-03 (High) Ledger names, including party accounts, reach the model provider unmasked

- **Who and what.** The client's own people and businesses (a payee loses the pseudonymity the product promises). Two
  paths, the first stronger and affecting every client that uses the new party accounts:
  1. **`history` and `related` in the prompt** (`classify/llm.py:318-357`). `history` sends `ledger__name` for every
     previously reviewed row of the same payee, and `related` sends `sibling.ledger.name` for sibling rows. Neither goes
     through `_Chart.usable`, so the `is_party_account` exclusion that keeps a party's own ledger out of `"ledgers"`
     (`classify/llm.py:164-168`, "its name would put a real party name in the prompt") does not apply. A party's own account
     is named after the party (`ledger/billing.py:244-279`), so once a payment has been placed on it through the settlement
     flow, the next batch for that payee sends `booked_to: "Ramesh Kumar Sharma"` next to the payee's alias token. The alias
     is defeated for exactly the people the pseudonymiser hides.
  2. **Imported charts.** `classify/llm.py:422-424` sends every usable ledger name in `"ledgers"`, and `usable` excludes a
     ledger only when a `Party` row points at it (`classify/models.py:147-156`). A Tally chart import creates ledgers for
     Sundry Debtors, Sundry Creditors and loans, often named after people or proprietors, and creates no `Party`
     (`ledger/tally_import.py` has no party handling). Until a bill is posted for that party, its name goes out in clear text.
  Do not remove the masking or the model tier; close these two channels.
- **Reproduction (by reading).** (1) Place and approve a payment for a person-named payee on that party's account, then
  run next-batch on another row with the same counterparty: the request body's `history` and `related` carry the party
  ledger's name. (2) Import a chart with a Sundry Creditor "Ramesh Kumar Sharma", upload a statement with an unresolved
  row, run next-batch: `ledgers` contains the name.
- **Fix direction.** Alias rather than remove. In `_context_for`, map any party-account ledger name to the party's alias
  token (a `Party` row exists, so `alias_token` is there) in both `history` and `related`, and send the ledger name only
  for ordinary ledgers. For imported charts, treat ledgers in the debtor, creditor, loan and capital groups as party-like
  in the prompt (exclude them from `usable`, or send an alias and map the model's answer back). Pass every ledger name and
  `business_profile` through `mask_text`. Add a test that builds the whole prompt for a client with person-named party
  and creditor ledgers and asserts no such name appears anywhere in it.

### A-04 (Medium) OpenAPI schema and API docs are public

- **Who and what.** Anyone on the internet. `config/urls.py:36-46` mounts `SpectacularAPIView`, Swagger UI and Redoc, and
  `SPECTACULAR_SETTINGS` does not set `SERVE_PERMISSIONS`, whose drf-spectacular default is `AllowAny`. The header comment
  in `config/urls.py` and `core/middleware/headers.py` says these sit behind the login; they do not. Caddy forwards
  `/api/*`, so this is reachable in production.
- **Evidence (confirmed).** Using Django's test client with the prod settings module and no session, no database:
  `/api/schema/` 200 (317,400 bytes), `/api/docs/` 200, `/api/redoc/` 200, while `/api/v1/me/` correctly gives 403.
- **Impact.** A free map of every endpoint, field and enum for an attacker, and the docs pages run with
  `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net` (`config/settings/base.py:_CSP_DOCS`), so a compromised CDN
  asset executes on the app's own origin, where the session cookie lives.
- **Fix direction.** Set `SERVE_PERMISSIONS` to `["api.permissions.IsFirmMember"]` and `SERVE_AUTHENTICATION` to session
  auth, or do not route the docs in production at all (keep them for DEBUG). If kept, self-host the Swagger and Redoc
  assets so the relaxed CSP can drop the CDN and `'unsafe-inline'`. Fix the stale comments and the test in
  `core/tests/test_hardening.py:213`, which assumes a login redirect.

### A-05 (Medium) Django admin login is unthrottled and public

- **Who and what.** An outsider guessing the platform owner's password. `/admin/login/` (`config/urls.py:47`) uses Django's
  admin login form and `EmailBackend`. The throttle in `core/throttle.py` is called only from `core/views.py` (login, MFA
  views) and the invite endpoint; nothing throttles the admin form. Caddy publishes `/admin/*` (`deploy/Caddyfile`
  `@backend`). The super admin is the one account with `is_staff`, can read every firm's directory, and edits users and
  passwords. MFA is still demanded after the password (the middleware gates `/admin/`), so this is a missing brake on stage
  one, not a bypass.
- **Fix direction.** Route the admin's login through the same throttled view (override `AdminSite.login`), or restrict
  `/admin/*` in Caddy to a known address range or a VPN, or serve it on a separate hostname with its own rate limit. Do
  both throttle and an IP allowlist if the owner works from a fixed network.

### A-06 (Medium) Audit trail integrity and coverage

- **Not append-only in the database.** `core_audit_log` is created with `rls_operations` only
  (`core/migrations/0002_row_level_security.py:27`), which grants SELECT, INSERT, UPDATE and DELETE to the app role.
  Append-only is enforced only in `AuditLog.save()` in Python (`core/models.py:498`), which `QuerySet.update()` and
  `.delete()` bypass. The journal, books events, entry changes and team events do use `append_only_operations`; the audit
  log, which is the record of who did what, does not. A bug or an injection in the web process can rewrite or erase it.
- **Coverage.** `AuditMiddleware` records only POST, PUT, PATCH and DELETE with a path (no body, no result detail)
  (`core/middleware/audit.py`). Reading a decrypted account number (`BankAccountDetailSerializer`), downloading a stored
  statement (`api/views/documents.py`) and reading party GSTINs are not audited, nor are failed or successful logins in the database trail (no
  firm context exists at login, so `AuditMiddleware._record` only logs a warning). Logins and MFA attempts are recorded, with
  masking, in the `autoca.security` log (CloudWatch), so the gap is the per-firm audit table the firm owner reads, not the
  absence of any record. Many routes added since the action
  table in `api/views/audit.py` was written (bills, settle, remove, bill-status, sign-off) show as raw "POST /path".
- **Fix direction.** Apply `append_only_operations("core_audit_log")` in a new migration (grants and trigger). Add audit rows
  for decrypting reads and document downloads and for authentication events (with the firm resolved from the membership of
  the user who just signed in). Extend the action table or log the resolved route name.

### A-07 (Medium, suspected) Upload cost and rate limits

- **GST uploads.** `gst/parsers.py:239-248` loads an `.xlsx` with `read_only=True` and then materialises every row:
  `[list(r) for r in ws.iter_rows(values_only=True)]`, with only the 25 MB file-size cap
  (`api/views/gst.py:62-68`). A 25 MB workbook can hold orders of magnitude more XML (zip compresses repetitive sheets
  roughly a thousand to one), and a sheet can declare up to 1,048,576 rows. The Tally importer guards exactly this (member
  count, unpacked-size sum and a row cap in `ledger/tally_parse.py:542-567`); the GST path does not. The production host is
  a 2 GB instance, so an out-of-memory kill takes the whole stack with it. Anyone with `gst.prepare` can send it.
- **No per-user or per-firm limit** on statement upload, `review-queue/suggest`, `review-queue/recategorize`, GST uploads
  or next-batch beyond the provider's own daily cap. Parsing is inline in the request (3 workers, 2 threads). The earlier
  page ceiling (300 pages) helps for statements; a PDF with few pages but pathological content streams is still parsed
  by pdfplumber and pdfminer in-process with no time or memory limit.
- **Fix direction.** Apply the Tally guards to the GST reader (count members, sum `file_size`, cap rows and columns, stop
  iterating at a limit). Add DRF throttles per user and per firm on the expensive POSTs, run parsing with a memory and
  time limit (a worker process with `RLIMIT_AS` and a timeout), and move extraction off the request thread when the queue
  lands.

### A-08 (Low, known) Login throttle

- `core/views.py:104-120` throttles on the email alone. Anyone can lock a named account (the owner included) for five
  minutes with ten wrong guesses, repeatedly, and one source can try nine passwords against every account without limit
  (credential stuffing). MFA reduces the impact. The reason in `core/throttle.py` (the proxy address was untrustworthy
  behind Vercel and Render) no longer applies on AWS: Caddy is the only proxy and `TRUSTED_PROXY_COUNT=1` is right. This is
  r1 finding SEC-007 / R1-09, which stays open.
- **Fix direction.** Count failures per address as well as per account, with a higher address threshold, and lock the
  (address, account) pair rather than the account alone. Use the Redis cache (already configured) so the counts are shared.

### A-09 (Low) Bank account create route

- `BankAccountViewSet` (`api/views/banking.py:197`) lists `post` in `http_method_names` and inherits `ModelViewSet.create`,
  with `POST: ledger.manage`. Every serializer field except `ledger_name` is read-only, so a Staff user can POST
  `{"ledger_name": "X"}` and get a `BankAccount` with an empty ciphertext, blank bank code and a blank hash. A second POST
  hits the unique constraint (500). The empty ciphertext makes `GET .../bank-accounts/{id}/` (which decrypts) fail, and the
  stray account name can collide with a real ledger name. The docstring says accounts are never created by hand.
- **Fix direction.** Remove `post` from `http_method_names` (the `opening-balance` action is a separate route and keeps
  working).

### A-10 (Low) Deploy pipeline

- `deploy/deploy.sh:18-25` runs `git pull --ff-only` and then only checks the tested commit is an ancestor of `HEAD`. It
  deploys whatever the checked-out branch tip is, so a later push to that branch ships untested code. Check out the exact
  commit (or fail unless `HEAD == $want`).
- `.github/workflows/deploy.yml` is sound where it matters: the `workflow_run` trigger is limited to a successful CI
  `push` on `prod` in this repository, the action is pinned by SHA, and the SSM document takes only a 40 hex character
  commit (`allowedPattern`). Not verifiable from the repo and worth checking in the console: the OIDC trust policy
  `sub` condition pins `repo:<owner>/<repo>:ref:refs/heads/prod` (and `aud`); the role's policy is limited to
  `ssm:SendCommand` on that one document and instance, plus `ssm:GetCommandInvocation`; the `prod` branch is protected
  (required reviews, no force push), because a push to `prod` is a root-equivalent deploy (the document runs a script as a
  user with sudo docker).
- `.github/workflows/ci.yml` has no `permissions:` block (set `contents: read`) and pins actions by tag
  (`actions/checkout@v4`, `setup-python@v5`, `setup-node@v4`), unlike deploy. `pip-audit` runs only on
  `requirements/base.txt`.
- The `web` container uses the instance role by design (S3 file storage signs with it, and `deploy/backup.sh` uploads through
  `compose exec web python -m integrations.backup.s3`), so containers must be able to reach the metadata service; do not
  set the IMDS hop limit to 1, which would break file storage and the nightly backup. Checks to make in the console:
  IMDSv2 is required (`HttpTokens=required`); the role's S3 permissions are scoped to the two named buckets, with the backup
  bucket put and list only (as `docs/AWS.md` says); CloudWatch permissions are limited to the one log group. The residual
  is accepted by design and should be named in the architecture notes: a compromised web process can read every firm's stored
  files with the role, and can write (not read or delete) backups.
- `Dockerfile:39` has `--forwarded-allow-ips "*"`. Safe only because port 8000 is on the private compose network; keep
  it that way (do not publish the port) or set it to Caddy's address.

### A-11 (Low, documented) Key custody

- Production uses `LocalFernetKMSAdapter` by default (`config/settings/base.py` `INTEGRATIONS`, `deploy/prod.env.example`).
  The master key and `BLIND_INDEX_KEY` are in `.env.prod`, which the internet-facing web container receives, so a code
  execution bug in the web process yields both the ciphertext access and the keys; database dumps in S3 stay protected
  only while those keys stay out of the dump. `docs/AWS.md` lists AWS KMS as not set up yet. Add a deploy-time system check
  that fails in production if the local adapter is selected once real client data exists, and move to the KMS adapter
  (`integrations/kms/aws.py`) with the instance role scoped to `kms:Decrypt` and `kms:GenerateDataKey` on one key.

### A-12 (Low) Deactivated user sessions

- `core/auth/backends.py:38-43` `get_user` returns the user without checking `is_active`, unlike Django's `ModelBackend`.
  Deactivating a login (admin sets `is_active=False`) therefore leaves any live session valid for up to eight hours.
  Membership deactivation, the normal path, is checked on every request (`core/middleware/tenancy.py`), so the practical
  window is the super admin disabling a user globally. Fix: return `None` from `get_user` when the user is inactive.

### A-13 (Low) Unbounded numbers

- `PaiseField` has no `max_value` (`api/fields.py:29`), although `core.money.MAX_PAISE` exists. A bill head, tax or
  opening amount of `10**30` passes validation and fails in PostgreSQL (`bigint` overflow), answering a generic 500 and
  logging a stack trace. `SettlementSerializer.allocations`, `RowSettlementSerializer` lists and `ApproveSerializer.classifications`
  have no `max_length`; each allocation takes row locks and a query pair. Add `max_value=MAX_PAISE` to `PaiseField` and a
  sensible `max_length` (a few hundred) on the lists.

### A-14 (Low) Dependencies

- `pip-audit --local` on the dev virtualenv reports `urllib3` 2.7.0 (PYSEC-2026-4175, 4176, 4177, fixed in 2.8.0) and
  `pytest` 8.4.1 (PYSEC-2026-1845, dev only). `urllib3` is not in `requirements/base.txt`; it comes in through boto3 and
  botocore, and the production image resolves whatever is newest at build time. Transitive packages are not pinned and
  there are no hashes, so two builds of the same commit can differ. Generate a lock file (`pip-compile --generate-hashes`
  or `uv pip compile`) for `base.txt` and install with `--require-hashes`, and run `pip-audit` on the lock.
- `npm audit --omit=dev` on `web/package-lock.json`: 0 vulnerabilities across 171 production dependencies. The lock file is
  used by `npm ci` in `web/Dockerfile.caddy`. Good.

### A-15 (Low) Search path in SECURITY DEFINER functions

- `superadmin/sql.py:63` sets `search_path = pg_catalog, public`. PostgreSQL searches the session's `pg_temp` schema first
  for relations unless it is listed last, so a session that can create a temporary table named `core_user` could make
  `app.superadmin_can_read()` and `app.superadmin_assert()` read attacker-controlled rows. It needs SQL execution as the
  app role, so it is defence in depth (and the app role has the default `TEMP` privilege). Use
  `SET search_path = pg_catalog, public, pg_temp` and schema-qualify the tables (`public.core_user`), and
  `REVOKE TEMP ON DATABASE ... FROM PUBLIC`.

### A-16 (Info) Model-only auto-post

- Rows placed only by the model with self-reported confidence 0.90 or higher post without a person
  (`ledger/approval.py:350-411`). The system prompt now marks narrations as untrusted (`classify/llm.py:92`) and sign-off is
  refused while assistant-posted entries are unchecked, which was the user's decision D1 = B. Residual risk is a payer's
  UPI remark steering a row between existing active ledgers until a person reviews it. Not re-opened; noted so it stays on
  the list.

---

## 3. What I checked and found sound

**Tenant isolation (RLS).**
- `core/db/session.py`, `core/db/rls.py`, `core/middleware/tenancy.py`: the tenant is set with `set_config(..., true)`
  (transaction scoped, bound parameter), refuses to switch firms mid-transaction, and is cleared in `finally`. The firm id
  comes from the authenticated user's membership, never from request input. The user GUC feeds one policy only
  (`app.membership_visible`).
- `FORCE ROW LEVEL SECURITY` plus a policy `TO autoca_app` on every firm table; the app login role `autoca_web` is
  NOSUPERUSER, NOBYPASSRLS, cannot create in `public`; the owner role lives in `.env.owner`, read only by the `migrate`
  service; `core/checks.py` turns role mistakes into deploy errors (E010, E011, E013) and `compose.prod.yaml` runs
  `check --deploy` on every release.
- Raw SQL: no `.raw(`, `.extra(`, `RawSQL`, or `using("owner")` anywhere outside migrations and tests. The only
  `connection.cursor()` uses are the tenant helpers and migrations. `firm_context(...)` call sites (views, `classify/queue.py`,
  management commands, `teams/service.py`, `superadmin/admin.py`, `scripts/qa_*.py`) all pass either the request's own firm,
  a firm read from a trusted row, or an operator-supplied CLI argument. `accept_invite` opens the firm context named in the
  invite link before anyone is signed in; the 256-bit secret must match an invite row in that firm, so a forged firm id
  reads nothing.
- BEFORE triggers must not set the tenant from `NEW.firm_id`. Checked every trigger: `classify/0010` and `ledger/0004`
  did, and were replaced by `classify/0020` and `ledger/0013`; `classify/0019` and `ledger/0012` (bill and allocation
  guards) do not. The functions that still call `set_config(... NEW.firm_id ...)`
  (`assert_entry_balances` in `ledger/0008`, `assert_allocation_sums` in `ledger/0012`, `core/db/rls.py:371`) are AFTER,
  DEFERRED constraint triggers that fire at commit: the row already passed `WITH CHECK` when it was written, so the value
  can only be the firm that owned the row. Worth a code comment and a regression test that asserts no BEFORE trigger
  function contains `set_config`.
- Super admin: cross-firm reads go only through SELECT-only views owned by a NOLOGIN BYPASSRLS role, each gated by
  `app.superadmin_can_read()` (active superuser with no firm membership) and `security_barrier`; firm staff cannot open
  `/admin` (`allow_admin` is `is_superadmin`, not `is_staff`); firmless access is limited to `/app`, `/admin`, `/auth/*`,
  `/api/v1/me/`.

**Authorisation and IDOR (every view in `api/` and `teams/`).**
- Client-scoped routes resolve the client through `get_visible_client`; by-id routes (`transactions`, `classifications`,
  `journal-entries`, `bank-accounts/{id}/reconciliation`, `documents`) filter with `visible_client_ids`. Ids inside request
  bodies are re-resolved inside the client and firm: approval `classifications` and `settlements` (restricted to
  `pending_approval(client)`), settlement `bill` ids (`api/views/settlement.py:settlement_from`), bill create `party`,
  `heads[].ledger` and `document` (`api/views/billing.py`), `correct` `ledger` and `party`, `review` `ledger` and `party`,
  `confirm-party`, ledger `merge into`, `recategorize statement`, rule `ledger` and `party`
  (`_reject_another_clients_objects`), GST `registration` and `match`, team member and client ids (`_any_member`,
  `_managed_client_or_404`). A client or object outside the caller's scope is a 404.
- Sign-off and posting rules (`core/access.py`) are re-checked inside the domain (`ledger/approval.py`, `ledger/billing.py`,
  `ledger/settlement.py`, `ledger/books.py`, `ledger/tally_import.py`), not only in views. `CanApprove` plus `can_post`
  or `require_posting_rights` on `settle`, `remove`, `bill-status`, `correct`, bill create and remove.
- Roles: team and membership changes (`teams/service.py`) enforce who may promote, invite and deactivate whom, owner
  protection, and the firm always keeping an admin.
- Mass assignment: the viewset serializers expose `firm`, `client`, status and lock fields as read-only
  (`ClientSerializer`, `PartySerializer.ledger`, `ClassificationRuleSerializer.client`, `BankAccountSerializer`). The one
  exception is A-01.
- Concurrency in settlement: `billing.allocate` locks the line and the bill, re-checks open amounts, and the database
  re-checks at commit (`assert_allocation_sums`). Duplicate bill entries in one settlement are summed (`Counter`) before the
  open-amount check.
- Journal, bill and allocation tables are guarded in the database: no UPDATE on bills or allocations, deletes refused for
  signed-off periods, same-client checks on every link, `signed_off_through` can only move back with the explicit
  `app.allow_reopen` setting.

**Authentication.** Session cookie (HttpOnly; Secure and SameSite=Strict in prod; 8 h), `login()` rotates the session key,
Argon2 hashing, twelve-character minimum with common and numeric validators, equalised timing for unknown emails, one
message for wrong email and wrong password, TOTP mandatory for every non-exempt path and enforced before the tenant
context opens, MFA failures throttled on address and user, `MFA_DISABLED` honoured only when `DEBUG` is true and a system
check errors if it is set otherwise, `next=` validated with `url_has_allowed_host_and_scheme`, invite secrets
`token_urlsafe(32)` stored hashed. A password-only session can enrol its own device on an account with none (expected for a
first login), but cannot add a device to an enrolled account (verify picks the confirmed device).

**Files and parsers.** Statement upload checks size, the `%PDF-` signature and a 300-page ceiling before extraction. Tally
import: defusedxml with DTDs and entities refused, size, ledger count, name length and zip member limits, formula-looking
names skipped, formats decided from bytes. GST export neutralises leading `= + - @ tab CR`. Exports: the only generated file is the GST working paper (server-side, neutralised as above); the web app has no
client-side CSV or Excel export (`web/src/platform/download.ts` only saves a server response or a text blob), so the new
party statements and outstanding reports, whose narrations are payer-controlled, have no export path to inject into yet.
Add the same neutralising helper before any export of them is built. Storage keys are always
`firms/<firm_id>/...` and verified on read (`verify_tenant_key`); the local adapter checks containment; downloads are
`Content-Disposition: attachment` with `nosniff` and `no-store`. No SSRF surface: the only outbound HTTP is to a fixed
base URL set by environment (`integrations/llm/groq.py`) and S3 through boto3. No shell, `subprocess`, `eval`, `pickle`
or unsafe YAML in application code.

**Injection and XSS.** All queries use the ORM or bound parameters. Templates auto-escape; the single `|safe` is the
library-generated QR SVG. The React app has no `dangerouslySetInnerHTML`, `innerHTML`, `eval` or token storage
(`localStorage` holds only UI preferences); external links use `noopener,noreferrer`. The strict CSP is set by Django on
every API response and by Caddy on the SPA (`style-src 'unsafe-inline'` only on the SPA shell, minor).

**CSRF, CORS and cookies.** Django's CSRF middleware covers every state-changing view including login; the SPA fetches a
token and sends `X-CSRFToken` with one retry; same-origin deployment through Caddy means no CORS package is installed or
needed; trusted origins come from `FRONTEND_URL`.

**Error handling and logging.** Unknown exceptions become a generic 500 body and a masked traceback in the log; job errors
for unexpected failures carry only a job id; log records pass through `MaskingFilter` (PAN, GSTIN, account, IFSC, phone,
card, e-mail, UPI id). Not-found and not-visible are the same 404.

**Secrets.** `git ls-files` contains only `.env.example` and `deploy/prod.env.example` (placeholders). A pattern scan of
tracked files and of the full history for AWS keys, Groq `gsk_` keys, private keys, GitHub and Slack tokens found nothing.
`.env*` is in `.gitignore` and `.dockerignore`, so the backend image does not contain them; `.env.owner` and `.env.db` are
read only by the services that need them. `scripts/qa_seed.py` holds a synthetic QA password only.

**Dependencies.** `npm audit --omit=dev`: 0 findings. See A-14 for Python.

**Infrastructure.** Only Caddy publishes ports (80, 443); database, Redis and the app are on the private network; Caddy
caps the body at 26 MB, hides source maps, and sets HSTS; SSM document restricted to a 40 hex character commit; no SSH.

---

## 4. Status of the earlier round (r1), as seen in the code now

- SEC-001 GST formula injection: fixed (`gst/report.py:203-212`).
- SEC-002 page ceiling: fixed for page count (`api/serializers/banking.py`); see A-07 for what is left.
- SEC-003 person names to the model: fixed in `pseudonymise.py`; A-03 is a different channel (ledger names).
- SEC-004 prompt injection: prompt hardened; auto-post policy accepted (A-16).
- SEC-005 GST 500s: fixed.
- SEC-006 weak person token: token still an unkeyed 32-bit hash (`classify/pseudonymise.py:person_alias`). Make it an HMAC with
  a per-firm secret from `core/crypto.py`.
- SEC-007 login lockout: interim only (A-08).

## 5. Suggested order of work

1. A-01 (guard ledger edits, with a database trigger), A-03 (alias party and creditor ledger names in the prompt), A-04 (close the schema).
2. A-02 (drop or sandbox user regexes), A-05 (throttle or restrict `/admin`), A-06 (append-only audit log).
3. A-07 (GST zip guard and per-user throttles), A-09, A-10, A-12, A-13, A-14.
4. A-08, A-11, A-15 as part of the AWS KMS and hardening step.
