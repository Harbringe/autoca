# Statement uploads in the background

## Why

Measured on the live server (a 238-page, 2,856-row statement, 2026-10-20):

| Uploads at once | Server time each |
|---|---|
| 1 | 34.6 s (19 s reading the PDF, 13 s auto-posting, 2 s classify) |
| 2 | 48.7 s and 71.3 s |

The work runs inside the web request (`core.jobs.run_job` calls the work inline), so a web worker is held for the whole time. The web server
has 3 workers x 2 threads and a 120 s timeout. Two uploads are safe; three or four at once would push the slowest past the timeout (a 502, with
the upload lost half-way) and, with 2 vCPUs, slow every other person's page while they run.

## What already exists (and does not change)

* `POST /clients/<id>/statements/upload/` answers `202` with a `Job`; a repeat of the same file returns the same job (idempotency key).
* `Job` has `PENDING / RUNNING / SUCCEEDED / FAILED`, `progress`, `message`, `result`, `error_code`. `PENDING` is unused today.
* The web app (`web/src/api/jobs.ts` `waitForJob`) already polls the job and shows its message and progress, and handles every error code.
* A worker process pattern exists: `classify/management/commands/run_assistant.py` (loops over `firm_ids()`, each in its own `firm_context`).
* Original files are kept through the storage adapter (`banking.ingest._store_original`, keyed under the firm's prefix).

## The change

1. **Accepting an upload is fast (well under a second).** The view decides first whether the upload is background-eligible (no password; see
   below), validates the file as today, puts the bytes in storage under the firm's prefix (`clients/<client>/uploads/<job id>.pdf`), creates the
   job as `PENDING` with the message "Waiting to be read", and returns `202`. If staging fails, no job is left behind and the person gets an error.
2. **A worker does the reading.** A new `python manage.py run_uploads` process (a `worker` service in `compose.prod.yaml`, same image as the
   assistant) runs jobs one at a time (`UPLOAD_WORKER_CONCURRENCY`, default 1).
3. **What the code does today (read, not assumed).** `core.jobs.run_job` wraps the whole of `_ingest` in one `transaction.atomic()`, so today a
   transaction stays open for the full ~35 s, PDF read included, and the job's final status is written *after* that transaction commits. The PDF
   read (`files.load`, `detect_parser`, `parser.parse`, the scanned-page reader) touches no database. A retry of an ingest whose file hash already has a
   statement returns the original statement without re-reading. Own-transfer pairing, invoice matching and auto-posting each act on the rows still
   pending, so running them again on a finished statement finds nothing to do; each gets a test that proves it rather than a claim.
4. **Transaction boundaries (a refactor, stated exactly).** `ingest_statement` is split into two parts: a **read** part (no database: load the file,
   parse it, prove it against the balances) that runs with no transaction open and takes ~19 s, then a **write** part (account, continuity checks, the
   stored original, document, statement, rows, then classify, pair, match, auto-post) that runs in one transaction in the firm's context. The
   stored original goes to storage before the transaction (its key is the file's hash, so putting it twice is harmless). Nothing in the write part
   calls an outside system; the optional scanned-page reader is in the read part.
5. **Claiming, leases and fencing.**
   1. *Claim* is its own short transaction: pick the next eligible `PENDING` job `FOR UPDATE SKIP LOCKED`; set `RUNNING`, `attempts += 1`, a new random
      `lease_token`, `worker_id`, `heartbeat_at = now()`; commit.
   2. *Lease checks use database time only* (`now()` in SQL, never the worker's clock). The worker checks it still holds the lease before it starts
      the write part.
   3. *The write transaction fences itself.* Its last statement is `UPDATE core_job SET status='SUCCEEDED', result=... WHERE id=? AND lease_token=?`,
      inside the same transaction as the work. If that updates no row the lease was lost, the worker raises, and **all of its writes roll back**. So a stale
      worker cannot leave rows, postings or matches behind: it commits everything together with the job's success, or nothing. Work and status commit
      atomically, which also closes today's gap where a crash between the two left finished work on a job still marked running.
   4. *If two workers did run the write part at once* (a paused process resumed after its job was requeued), they collide on the unique file hash and
      the loser's transaction fails and rolls back; the lease fence stops any that did not collide.
   5. *Failures* are recorded in a separate short transaction with the same `WHERE ... AND lease_token = ?` guard.
6. **Heartbeat and recovery.** A thread in the worker sets `heartbeat_at = now()` (database time, guarded by the token) every 20 s through every
   stage. Recovery is one conditional statement: back to `PENDING` with the token cleared where `status = 'RUNNING'` and `heartbeat_at` is older than
   5 minutes by database time and `attempts < 3`; `FAILED` ("The reader stopped while reading this file; upload it again") where `attempts >= 3`.
   Attempt 1 is the first run, 2 and 3 are recoveries. The staged file stays until the job is final.
7. **Fairness, stated exactly and stateless.** Among firms with an eligible `PENDING` job, rank by the finish time of that firm's most recent upload job
   of *any* terminal status (a failure counts as being served), never-served firms first, then oldest finish first, ties by firm id. Within the chosen
   firm: `created_at`, then job id. Computed from the job table on each claim, so a restart loses nothing. (A firm last served months ago correctly
   goes ahead of one served a second ago; that is what "longest wait since service" means.)
8. **Staging is content-addressed and idempotent.** The staged key is `clients/<client>/uploads/<file hash>`, so two simultaneous requests for the same
   file write identical bytes to one object. The existing unique constraint on the idempotency key decides the winner: the loser returns the winner's
   job and deletes nothing. An object is deleted only when its job is final **and no other non-final job references the same key**. If storage
   succeeds and job creation then fails, the object is an orphan; a periodic sweep (every worker loop, at most hourly) removes objects under
   `uploads/` older than an hour that no non-final job references. (This needs the storage adapter to list a prefix: checked when the staging step is
   built, and added to the local and S3 adapters if missing.)
9. **Cleanup order.** The final state commits first, then the staged object is deleted. A failed delete is logged and left for the sweep; it never
   changes a job's result.
10. **Progress.** Stage boundaries only ("Reading the PDF", "Placing rows", "Matching invoices", "Posting what the rules are sure of"). Waiting jobs say
    "N ahead of you", approximate by nature and shown as such, not an ETA.
11. **A switch.** `STATEMENT_UPLOAD_MODE = inline | background`. Tests and local development stay `inline`; production is `background`.
12. **Health is three separate signals** written to the cache by the worker: *last successful queue poll*, *last successful job heartbeat*, and
    *the job it is on (id and attempt)*. The container health check and the web notice use them. The web says "the reader is not running" only when
    jobs are waiting **and** the queue poll is missing or older than 2 minutes. A pending job alone is not proof the worker is down: if the poll is
    fresh and a job is running it says "reading another file, N ahead".
13. **Accepting is fast, and that is a target, not a promise.** Validation, storage I/O and job creation have to happen in the request. It is
    measured against realistic storage latency and concurrent requests (see the tests and the live run), not asserted.

### What serial processing does and does not promise

Serial processing bounds concurrent ingestion to the configured concurrency. Upload requests return right after staging, so ingestion no longer
occupies web workers and is no longer governed by the web request timeout. Queue wait depends on the jobs ahead and is monitored separately; it
is not promised to stay under any limit. After deploy the worker's job durations, including the slow tail, are read from its log line
(the same "statement upload: ..." line, with queue wait added) and judged against real data.

### Decisions that need to be right

* **Password-protected PDFs stay inline.** The password is deliberately never stored (not in the job, the key, a message or the database). The
  decision is made before anything is staged: a request carrying a password never creates a staged file or a pending job, so no background worker
  can pick up a file it cannot open. A wrong or missing password fails in the request as it does today, leaving nothing behind.
* **The uploaded file is staged in storage, not in the database**, so large files never sit in a table and the tenant-prefixed key scheme
  guarantees no cross-firm key.
* **No new infrastructure.** No Celery, no broker. The database is the queue; the volume (tens of uploads a day) is far below what that handles,
  and the server has no room for another daemon.
* **New `Job` columns** (one migration): `attempts`, `lease_token`, `worker_id`, `heartbeat_at`, `staged_key`.

## Web app

Almost nothing: `waitForJob` already polls `PENDING`. Changes: show "Waiting to be read - N ahead" while `PENDING`; keep the dialog usable (a
person can close it and carry on; the Statements list shows a "Reading..." row from the job); if a job has been `PENDING` for over 2 minutes since it was queued and the worker's own heartbeat (the cache value above, not the job's, since a queued job
has never been claimed) is missing or old, say "The reader is not running; the file is safe and will be read when it starts".

## Tests

* Accepting returns 202 in a fixed small number of queries and stores the file; the job is `PENDING`; a storage failure leaves no job.
* One worker pass turns it `SUCCEEDED` with the same result the inline path gives: same statement contents, row counts, dedupe, posting results.
* Same file twice while pending returns the same job; after success returns the original.
* Every error code the inline path produces comes back identically from the worker.
* Two workers claim concurrently: they cannot take the same job.
* A worker that lost its lease cannot write a result or a heartbeat over the newer owner's job, **and its statement, rows, postings and matches are rolled back**, not left behind.
* Two simultaneous uploads of the same file: one job, one staged object, the loser deletes nothing; an object whose job creation failed is swept, one a pending job references is not.
* Fairness ties and failures: a firm whose last job failed counts as served; equal finish times order by firm id.
* Health: a worker whose queue poll is stale shows the "not running" notice; a busy but polling worker does not.
* Crash after the ingest committed but before the job was marked done: the retry duplicates no statement, row, posting or match.
* Attempts: crash twice and it runs a third time; crash a third time and it fails with the stated message.
* A long job keeps its heartbeat through every stage and is not requeued.
* Fairness: a firm with many uploads does not delay another firm's one; the order survives a worker restart.
* Two firms are read in their own tenant contexts; a firm never sees another's job.
* A password upload stays inline, stages nothing, leaves no job (including when the password is wrong), and the password appears nowhere persisted.
* The staged file is deleted after success and after failure; a failed delete leaves a successful job successful and is swept later.

## Order of work

1. `core.jobs`: split `run_job` into `enqueue_job` and `execute_job` (inline mode still calls both); tests.
2. Staging and the worker command with claim, heartbeat and requeue; tests.
3. The upload view in background mode; progress messages from `_ingest`; tests.
4. Compose `worker` service (memory-limited), deploy checklist, health via heartbeat.
5. Web: waiting text, stale-worker notice.
6. Re-run the live tests: 1, 2 and 4 uploads at once (large statements, several clients; more than one firm is covered by the tests and the scratch
   server, since live has one real firm), recording queue wait, execution time per job, worker and web memory, worker health signals, and the latency of
   unrelated page requests throughout. A successful upload alone does not show the original problem is solved; unaffected pages and no timeouts do.

## Not in this change

* Faster reading itself (19 s) and auto-posting (13 s). Worth profiling next; the queue makes them matter less, not zero.
* Moving the Tally, loan-statement and GST imports onto the same queue. The mechanism is generic (`kind` on the job), so each is a small follow-up.
