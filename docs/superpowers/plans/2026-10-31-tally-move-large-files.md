# Moving a firm's Tally history in: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A firm can hand over a year (or years) of Tally vouchers as one large export; it is read in the background, split into one queued import per month, posted oldest first with "Post all", and checked against Tally's trial balance.

**Architecture:** Files above the current 10 MB limit are stored as the client's document and read by a worker (job kind `tally.read`), which splits the vouchers by calendar month and stages one `LedgerImportRun` per month through the existing `_stage`. Posting stays the existing `tally.post` job; "Post all" queues each month's job in date order. The trial-balance check is a read-only comparison endpoint.

**Tech Stack:** Django/DRF, the existing `core.jobqueue` worker (`manage.py run_uploads`), React/TanStack Query, pytest (DB tests need the local Postgres on port 5434, never the live tunnel on 5433).

**Spec:** `docs/superpowers/specs/2026-10-31-tally-move-large-files-design.md`

## Global Constraints

- XML vouchers files up to 150 MB, JSON up to 100 MB; files up to 10 MB are still read inside the request, as now (one run for the whole file).
- Ledger lists and voucher-type files keep their small limits.
- One queued import per calendar month of voucher dates; a voucher is in exactly one.
- A voucher already imported (Tally id) is never written twice; entries already in a period are a warning the accountant ticks past.
- Nothing in a signed-off period is changed.
- Only DB tests against `localhost:5434`: always `export DATABASE_URL=postgresql://autoca_ci:ci@localhost:5434/autoca DATABASE_OWNER_URL=...5434...` after sourcing `E:\autoca-local\env.sh`.
- No push or deploy until the user says so in words that name it.

## Review Focus

- A big file spanning two financial years: months on both sides of 31 March each get their own run with the right `financial_year`.
- One month of the file already has entries in the books: that month's run is created with the overlap warning, the other months are unaffected.
- The same big file uploaded twice: the second upload reuses the first's runs, creates nothing new.
- A file with vouchers from two companies: refused whole, with the existing message, and no runs created.
- A month in which nothing can be posted (all left out): the run still exists and says why, and "Post all" skips it.
- The worker stops part-way through reading: the retried job finishes without duplicate runs.
- A file larger than the limit: refused with a message naming the limit, before it is read.

---

### Task 1: Limits for large vouchers files, and the proxy

**Files:**
- Modify: `config/settings/base.py` (near `MAX_TALLY_IMPORT_BYTES`, line ~448)
- Modify: `api/serializers/tally.py` (`TallyVouchersUploadSerializer.validate_file`)
- Modify: `deploy/Caddyfile` (the `request_body` block, line ~14), `deploy/nginx.conf` (`client_max_body_size`)
- Test: `api/tests/test_tally_vouchers_api.py`

**Interfaces:**
- Produces: settings `MAX_TALLY_VOUCHERS_XML_BYTES = 150 * 1024 * 1024`, `MAX_TALLY_VOUCHERS_JSON_BYTES = 100 * 1024 * 1024`, `TALLY_SYNC_READ_BYTES = MAX_TALLY_IMPORT_BYTES` (files at or below this are read in the request); `def voucher_file_limit(filename: str) -> int` in `ledger/tally_vouchers.py` returning the JSON or XML limit by extension.

- [ ] **Step 1: Write the failing tests** in `api/tests/test_tally_vouchers_api.py`: `test_a_vouchers_file_over_its_limit_is_refused_naming_the_limit` (settings override `MAX_TALLY_VOUCHERS_XML_BYTES = 1000`; a 2000-byte `.xml` upload gets 400 whose message contains "MB" or the limit), and a unit test `test_voucher_file_limit_is_by_extension` asserting `.json` returns the JSON limit and `.xml` the XML limit.
- [ ] **Step 2: Run** `pytest api/tests/test_tally_vouchers_api.py -k limit -q` — expect FAIL (names undefined).
- [ ] **Step 3: Implement** the three settings, `voucher_file_limit`, and make `validate_file` use it (the size check no longer uses `MAX_TALLY_IMPORT_BYTES * 2` for vouchers). Raise the Caddy `max_size` for the vouchers path only: add a `@tallyupload path_regexp` handle with `max_size 160MB`; nginx `client_max_body_size 160m` likewise. Keep 26 MB for every other path.
- [ ] **Step 4: Run** the tests — expect PASS; `caddy validate` is not available locally, so state that in the commit message and verify on deploy.
- [ ] **Step 5: Commit** "Tally: vouchers files up to 150 MB (XML) / 100 MB (JSON)".

### Task 2: Split vouchers by month

**Files:**
- Create: `ledger/tally_split.py`
- Test: `ledger/tests/test_tally_split.py` (pure, no database)

**Interfaces:**
- Consumes: `ledger.tally_vouchers.ParsedVoucher` (has `.date: datetime.date`).
- Produces: `def split_by_month(vouchers: Sequence[ParsedVoucher]) -> list[tuple[str, list[ParsedVoucher]]]` — `("2025-04", [...])` per month, ascending, every voucher in exactly one, original order kept inside a month.

- [ ] **Step 1: Write failing tests**: `test_vouchers_are_grouped_by_month_in_date_order`, `test_a_year_boundary_gives_separate_months` (vouchers on 2025-03-31 and 2025-04-01 → `"2025-03"` then `"2025-04"`), `test_every_voucher_lands_in_exactly_one_month`, `test_no_vouchers_gives_no_months`.
- [ ] **Step 2: Run** `pytest ledger/tests/test_tally_split.py -q` — expect FAIL (module missing).
- [ ] **Step 3: Implement** `split_by_month` with a dict keyed by `f"{d.year}-{d.month:02d}"`, returned sorted by key.
- [ ] **Step 4: Run** — expect PASS. **Step 5: Commit** "Tally: split vouchers by month".

### Task 3: Read a large file in the background, one run per month

**Files:**
- Create: `ledger/tally_read.py`
- Modify: `ledger/tally_voucher_import.py` (expose `stage_month`), `core/management/commands/run_uploads.py` (import `ledger.tally_read`), `api/views/tally.py` (`vouchers` action), `api/urls.py` only if a new route is needed
- Test: `ledger/tests/test_tally_read.py`, `api/tests/test_tally_vouchers_api.py`

**Interfaces:**
- Consumes: `_keep_file(client, user, data, filename) -> Document`, `_stage(client, user, all_vouchers, skipped, digest, date_from, date_to, type_map, document)`, `parse_vouchers(data, filename, *, max_bytes)`, `split_by_month`, `core.jobs.enqueue_job`/`mark_staged`, `core.jobqueue.register`.
- Produces: `KIND = "tally.read"`; `def enqueue_read(client, membership, user, *, data: bytes, filename: str, voucher_types: dict | None) -> JobResult` (stores the file as a Document, enqueues, payload `{"client", "document", "voucher_types"}`; idempotency key `tally-read:{client.pk}:{sha256}:{types digest}`); worker `run(ctx)` completing with `{"runs": [run_id, ...], "months": int, "failed": [{"month": str, "reason": str}]}`; `def stage_month(client, user, month_vouchers, skipped, month: str, seed: str, type_map, document) -> tuple[LedgerImportRun, bool]` whose digest is `sha256(f"{seed}|{month}")`.
- API: `POST tally-imports/vouchers/` answers `202` with the job (`JobSerializer`) when the upload is larger than `TALLY_SYNC_READ_BYTES`; unchanged `200/201` run otherwise.

- [ ] **Step 1: Write failing tests** (DB): `test_a_year_file_becomes_one_queued_import_per_month` (build a `vouchers_xml` of vouchers in April and May, call `enqueue_read` then `jobqueue.run_once("t")`, assert two PREVIEW runs with `counts["date_from"]` in their months and the same `document`), `test_the_same_big_file_twice_makes_no_new_runs`, `test_two_companies_refuse_the_whole_file`, `test_a_month_with_entries_still_gets_a_run_with_the_overlap_warning`, `test_a_file_spanning_march_and_april_gets_the_right_financial_years`; API test `test_a_large_upload_answers_202_with_a_job` (settings override `TALLY_SYNC_READ_BYTES = 100`).
- [ ] **Step 2: Run** `pytest ledger/tests/test_tally_read.py -q` — expect FAIL.
- [ ] **Step 3: Implement** `stage_month` (a thin wrapper over `_stage`), `enqueue_read`, and the handler (load bytes from storage, parse, refuse >1 company, split, stage each month in its own `transaction.atomic`, collect per-month failures, `ctx.say(f"Read {n} of {m} months")`, `ctx.complete(...)`). Register the module in `run_uploads`. In the `vouchers` view branch on `upload.size`.
- [ ] **Step 4: Run** the tests — expect PASS. **Step 5: Commit** "Tally: large vouchers files are read in the background, one import per month".

### Task 4: Post all

**Files:**
- Modify: `ledger/tally_jobs.py`, `api/views/tally.py`, `api/serializers/tally.py`, `api/urls.py`
- Test: `ledger/tests/test_tally_jobs.py`, `api/tests/test_tally_vouchers_api.py`

**Interfaces:**
- Consumes: `enqueue_post(run, membership, user, *, allow_overlap) -> JobResult`.
- Produces: `def enqueue_post_all(client, membership, user, *, allow_overlap: bool) -> list[LedgerImportRun]` (every VOUCHERS run of the client in `PREVIEW` status, not posting, with `counts["will_post"] > 0`, queued in ascending `counts["date_from"]`); `POST tally-imports/post-all/` body `{"allow_overlap": bool}` → `202 {"queued": int}`.

- [ ] **Step 1: Write failing tests**: `test_post_all_queues_each_waiting_month_oldest_first` (three months, assert job creation order matches date order), `test_post_all_skips_a_month_with_nothing_to_post`, `test_post_all_refuses_a_month_with_entries_unless_allowed` (409 `tally_overlap` naming nothing posted for any month before the refusal — decide: queue none if any month needs consent).
- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement** `enqueue_post_all` (check every month first with `check_postable`; only then queue, so a refusal queues nothing) and the endpoint with its route.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** "Tally: post all waiting months oldest first".

### Task 5: The screen — large upload, months, Post all, progress by year

**Files:**
- Modify: `web/src/api/queries/tallyImport.ts`, `web/src/features/tally/TallyImportScreen.tsx`, `web/src/features/tally/ImportQueue.tsx`
- Create: `web/src/features/tally/MoveProgress.tsx`
- Test: `web/src/features/tally/TallyImportScreen.test.tsx`, `web/src/features/tally/MoveProgress.test.tsx`

**Interfaces:**
- Consumes: `POST …/vouchers/` returning `200/201` run or `202` job; `GET …/jobs/{id}/`; `useVoucherRuns`; `POST …/post-all/`.
- Produces: `useStageVouchers` returns `{ run } | { job }`; `usePostAll(clientId)` (`mutate({allowOverlap})`); `MoveProgress({ runs, ledgerCount }: { runs: VoucherRunSummary[]; ledgerCount: number })` showing the three steps of the move as a checklist (1 "Ledgers brought in" done when `ledgerCount > 0`; 2 "Voucher types" shown as optional; 3 "Vouchers by year") and, under step 3, runs grouped by financial year (from `counts.date_from`) with posted / waiting / posting counts per year.

- [ ] **Step 1: Write failing tests**: a 202 answer shows "being read" and, when the job succeeds and the queue lists months, shows "12 imports" grouped (`test_a_large_file_shows_it_is_being_read_then_the_months`); `test_post_all_posts_the_waiting_months` (button calls `…/post-all/` with `{allow_overlap: false}`); `MoveProgress` renders "FY 2025-26: 12 waiting" and "FY 2024-25: 12 posted" from a fixture.
- [ ] **Step 2: Run** `npx vitest run src/features/tally` — expect FAIL. **Step 3: Implement** the hook changes, the polling of the read job, the Post all button (disabled while any month is posting; the overlap tick-box applies to all), and `MoveProgress` above the queue list.
- [ ] **Step 4: Run** `npx tsc --noEmit` and the vitest files — PASS. **Step 5: Commit** "Tally screen: large files, months, post all, progress by year".

### Task 6: Check against Tally's trial balance

**Files:**
- Create: `ledger/tally_trialbalance.py`
- Modify: `api/views/tally.py`, `api/serializers/tally.py`, `api/urls.py`, `web/src/features/tally/TrialBalanceCheck.tsx` (new), `web/src/features/tally/TallyImportScreen.tsx`, `web/src/api/queries/tallyImport.ts`
- Test: `ledger/tests/test_tally_trialbalance.py` (pure reader), `api/tests/test_tally_vouchers_api.py`, `web/src/features/tally/TrialBalanceCheck.test.tsx`

**Interfaces:**
- Consumes: `ledger.reports.trial_balance(client, year)` rows (`name`, `closing_debit_paise`, `closing_credit_paise`), `ledger.tally_parse.normal_name`.
- Produces: `def read_trial_balance(data: bytes, filename: str, *, max_bytes: int) -> dict[str, int]` (ledger name → closing paise, debit positive; XML `DSPACCNAME`/`DSPCLDRAMT`/`DSPCLCRAMT` and the JSON twin; UNVERIFIED against a real file, as the other readers); `@dataclass(frozen=True) class Difference: name: str; tally_paise: int; ours_paise: int`; `def compare(client, year: int, tally: dict[str, int]) -> tuple[list[Difference], int]` (differences, matched count; names compared with `normal_name`; ledgers on one side only appear with 0 on the other); `POST tally-imports/check-trial-balance/` multipart `file` + `fy` → `{"matched": int, "differences": [{"name", "tally_paise", "ours_paise"}]}`.

- [ ] **Step 1: Write failing tests**: reader reads a generated XML and its JSON twin to the same dict; `compare` reports a ledger that differs and a ledger only one side has, and counts matches; API returns 200 with differences and 400 for a non-xml/json; the screen test lists a difference row and a "Everything matches" message for none.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** reader, `compare`, endpoint, and `TrialBalanceCheck` (file chooser, year from the client's selected year, a table of differences).
- [ ] **Step 4: Run** all new tests — PASS. **Step 5: Commit** "Tally: check the posted books against Tally's trial balance".

### Task 7: Docs, schema, whole-branch verification

**Files:**
- Modify: `docs/ARCHITECTURE.md` (the Tally section), `web/openapi.yaml`, `web/src/api/schema.d.ts`

- [ ] **Step 1:** Update the architecture section for the monthly queue, the read job, post-all and the trial-balance check, and replace "no file is kept".
- [ ] **Step 2:** `PYTHON=…/python.exe npm run gen:api` in `web/`; confirm `manage.py spectacular` shows no drift.
- [ ] **Step 3: Run** `ruff check .`, `manage.py makemigrations --check --dry-run` (expect none: this plan adds no model), `npx tsc --noEmit`, `npx vitest run`, and the DB tests `pytest ledger api banking -k "tally or learn or evidence or background or vtypes or split or trialbalance"` on port 5434 — all PASS.
- [ ] **Step 4: Commit** "Docs and schema for the Tally move". Do not push.
