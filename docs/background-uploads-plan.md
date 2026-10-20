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
3. **Claiming is a short transaction, the work is outside it.**
   1. In one short transaction: select the next eligible `PENDING` job `FOR UPDATE SKIP LOCKED`, set `RUNNING`, `attempts += 1`, a fresh
      `lease_token` (random) and `worker_id`, `heartbeat_at = now`; commit.
   2. Run `_ingest` inside the firm's context with no transaction held open across the PDF read.
   3. In a separate transaction write the outcome with `... WHERE id = ? AND lease_token = ?`. Zero rows updated means the lease was lost (the job was
      requeued and someone else owns it): the old worker discards its result and does nothing else. The same guard applies to every heartbeat.
4. **Leases and crash recovery.** A thread in the worker refreshes `heartbeat_at` every 20 s for as long as the job runs, through every stage, so a
   long read is never mistaken for a dead worker. A `RUNNING` job whose heartbeat is older than 5 minutes is requeued (`PENDING`, token cleared).
   `attempts` counts executions: attempt 1 is the first run, 2 and 3 are recoveries; if attempt 3 also dies the job is `FAILED` with "The reader
   stopped while reading this file; upload it again". The staged file stays until the job is final.
5. **Retry safety (verified before relying on it).** Work already committed when the worker died must not be done twice: the statement is deduped by
   file hash (re-ingest returns the original), but auto-posting, own-transfer pairing and invoice matching each get checked and tested for being
   safe to run again on the same statement. Any that is not is made so before this ships. The ingest work and its own writes stay in one transaction,
   as `run_job` has it today, so a crash mid-way leaves nothing half-done.
6. **Fairness, stated exactly, with no state to lose.** Among firms that have an eligible `PENDING` job, take the firm whose most recently
   *finished* upload job is oldest (never-served firms first); within that firm take its oldest job. That is derived from the job table on every claim,
   so a restart loses nothing, and a firm with twenty files cannot hold up a firm with one.
7. **Progress people can see.** Stage boundaries only ("Reading the PDF", "Placing rows", "Matching invoices", "Posting what the rules are sure of"),
   never per row or page. Waiting jobs show "N ahead of you", which is approximate by nature (other jobs finish or arrive between polls) and is
   shown as such, not as an ETA.
8. **Cleanup in the right order.** The final state is committed first; then the staged file is deleted. If the delete fails it is logged and left for
   a periodic sweep (the worker removes staged files whose job is final or gone, older than an hour). A cleanup failure never changes a job's result.
9. **A switch.** `STATEMENT_UPLOAD_MODE = inline | background`. Tests and local development stay `inline`; production is `background`. Rolling back
   is one setting.
10. **Health means progress, not just life.** The worker writes a "last loop" and "last job heartbeat" time to the cache. The health check and the
    web notice below use those, so a process stuck in a database wait counts as down.

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
* A worker that lost its lease cannot write a result or a heartbeat over the newer owner's job.
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
6. Re-run the live tests: 1, 2 and 4 uploads at once, with a probe of other pages throughout; expect nobody's pages to slow noticeably and no upload to fail.

## Not in this change

* Faster reading itself (19 s) and auto-posting (13 s). Worth profiling next; the queue makes them matter less, not zero.
* Moving the Tally, loan-statement and GST imports onto the same queue. The mechanism is generic (`kind` on the job), so each is a small follow-up.
