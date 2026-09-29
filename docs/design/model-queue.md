# Q-1: a durable queue for the model tier

Status: design note, nothing implemented. Driver: the open browser (user's choice).

## The problem

`api/views/banking.py:_ingest` runs ingest, rules, `suggest_unresolved` and auto-post in one request and one transaction. `classify/llm.py:_suggest` returns on the first `LLMError` and abandons every later batch, after the Groq adapter has already slept through up to six rate-limit retries of up to a minute each. Rows the model never saw look exactly like rows it declined, so nothing retries them, and a retried upload doubles the whole wait (R1-10).

## 1. The upload stops calling the model

`_ingest` keeps: ingest, `seed_client`, `classify_statement`, `auto_post_client`. It drops `suggest_unresolved`. The job result gains `waiting_for_assistant` (the count of marked rows) in place of `model_suggested/declined/error`. The upload's transaction now holds only database work and ends in seconds. `POST /classifications/suggest/` stays as a manual "ask about everything again" that simply re-marks rows as waiting instead of calling the model inline.

## 2. Marking a row as waiting

Derivable today? Partly, and not safely. "Unresolved, no rationale, no question" is true of a row the model has not seen, but also of a row the model returned nothing for, so such a row would be re-asked on every poll and burn tokens forever. It needs an explicit fact, so the recommendation is **one nullable column, MIGRATION**:

`TransactionClassification.model_state` (CharField, null/blank, values `waiting`, `claimed`, `done`, `declined`; default null = never queued) plus `model_claimed_until` (DateTimeField, null) and `model_attempts` (small int, default 0). Adding the nullable columns is cheap on Postgres 11+ (no rewrite; brief lock only). The partial index on `(firm, model_state)` where state is `waiting` blocks writes while it builds unless it is created with `AddIndexConcurrently`, which needs a non-atomic migration; on a table this size, plain `AddIndex` is fine too, but the choice is the user's. Reversible by dropping the index and columns. Ingest sets `waiting` on every row still unresolved after the rules. Existing rows stay null and are never touched, except by the manual button.

A fallback with no migration exists (treat "unresolved and `rationale=''`" as waiting, cap re-asks by time in the cache) but it re-asks declined rows and loses attempt counts; I do not recommend it.

## 3. The batch endpoint

`POST /api/v1/clients/{client_id}/assistant/next-batch/`, no body (optionally `{"max_rows": 10}`, capped at 15). Permission `transaction.classify`, client-scoped like the other client routes.

Response 200:
`{"processed": n, "suggested": n, "declined": n, "waiting": n_left, "state": "working" | "idle" | "paused", "retry_after_seconds": int|null, "reason": ""|"rate_limit"|"daily_limit"|"provider_down", "message": "plain words"}`.

One call is bounded to about 20 seconds: the adapter gets a no-sleep mode (`wait_on_rate_limit=False`) and a single attempt with a 15 s timeout, so a call cannot sit in a backoff. It works in three phases, never holding a transaction or row lock across the model call (that would recreate OPS-002 and block a reviewer who places a claimed row): (1) claim and commit, (2) call the model with no transaction open, (3) apply the results and commit, each phase in its own `firm_context`, the pattern the job-events stream now uses. **Needs a decision:** if the tenancy middleware wraps the whole request in one transaction, this endpoint has to opt out of it and open its own phases; that is the most sensitive file in the repo, so the orchestrator decides, and the RLS suite runs after.

## 4. Two browsers, no double work

The claim is `SELECT ... FOR UPDATE SKIP LOCKED` over rows with `model_state='waiting'` (or `claimed` with `model_claimed_until` in the past), `LIMIT 10`, oldest statement first; the same statement sets `claimed` and `model_claimed_until = now + 60 s`. A second browser's call skips the locked rows and takes the next ten, or answers `idle` when none remain. A crashed call's claim lapses after 60 s and the rows are picked up again. `model_attempts` counts claims; at 3 the row becomes `declined` with a plain reason, so a poison row cannot loop.

## 5. Failure modes

- Rate limit (429, or 413 with `rate_limit_exceeded`): the adapter raises a typed `LLMRateLimited(retry_after, daily)` instead of sleeping. Rows go back to `waiting` (claim released, attempts not counted), the response is `state: paused, reason: rate_limit, retry_after_seconds`.
- Daily limit (Groq's tokens-per-day message, or a retry-after over ~10 minutes): `reason: daily_limit`, message "The assistant has used today's allowance; the remaining N rows wait for a person or for tomorrow". The endpoint answers the same without calling the provider again until the retry-after time, kept in the cache per firm, so polling costs nothing.
- Provider outage or malformed reply (5xx, timeout, `LLMError`): `reason: provider_down`, rows released, attempts counted once per row; back off 30 s, 60 s, 120 s.
- The stub adapter (model off): the endpoint answers `idle` with `reason: "assistant_off"` and leaves every row's state unchanged, so switching the model on later picks them up. The frontend stops polling on `idle`.

In every case the rows stay reachable by a person in the review queue; waiting rows are already listed there.

## 6. What the frontend does

While a client is open and `waiting > 0`, the workspace calls next-batch, then again after `retry_after_seconds` (default 3 s), pausing when the tab is hidden or the user leaves the client. It reads the same count from `GET /clients/{id}/` (or the review summary) on load, so a reopened client resumes at once. It shows one line: "The assistant is reading 40 of 120 rows", "Paused: rate limit, resuming in 40 s", or "Assistant allowance used for today, 30 rows left for you". The review list refetches after each batch that suggested something.

## 7. Moving to Celery later, unchanged

The unit of work is `process_next_batch(client)`: claim, ask, apply, release. The endpoint is a thin call to it. A worker runs the same function in a loop (or per beat tick) for every client with waiting rows, using the same `SKIP LOCKED` claim, so browsers and workers can run together and never overlap. The response shape stays; the frontend just finds `waiting` falling without its own calls, and the polling becomes read-only. No schema change is needed at that point.

## Open decisions for the orchestrator

1. Approve the migration (three nullable columns, one partial index).
2. Where the daily-limit retry-after is stored (cache is fine; hosted Redis quota means one key per firm, not per poll).
3. Whether R1-10's idempotency key is still wanted for the upload once the model call is gone (likely yes, cheaply).
