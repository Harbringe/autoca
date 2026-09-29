# DevOps / deployment review — round r1

Covered: `Dockerfile`, `compose.yaml`, `deploy/`, `config/settings/{base,prod}.py`,
`core/checks.py`, `core/http.py`, `core/throttle.py`, `core/jobs.py`,
`core/middleware/{audit,tenancy}.py`, `banking/ingest.py` call path,
`classify/llm.py`, `integrations/queue/*`, `integrations/storage/r2.py`,
`web/vercel.json`, `web/vite.config.ts`, `web/src/api/client.ts`,
`.github/workflows/ci.yml`, `docs/ARCHITECTURE.md`, `scripts/supabase_keepalive.py`,
`.env.example`, names-only of the local `.env`, `git log --all` for any env file
ever committed, gunicorn's own source for how `--workers`/`--threads`/`--timeout`
actually behave, and one safe local run of `manage.py check --deploy` (no
`--database`, no writes) against `config.settings.prod`. Passive reads against
`https://autoca-juie.onrender.com` and `https://autoca-jade.vercel.app` (GET only:
`/healthz`, `/`, `/admin/`, `/auth/csrf/`, static assets and their `.map`
counterparts, one `Host:`-spoofed GET, one `OPTIONS` on `/api/me/`). Not done:
anything needing the Render/Vercel/Supabase/Upstash dashboards, any timing test
that would need a loop or a real large PDF against production, and confirming the
actual value of any production env var (rule 3 — names only, never opened).

## If you only do three things

1. **`--workers 3` in the Dockerfile silently overrides Render's
   `WEB_CONCURRENCY` (OPS-011).** Gunicorn itself defaults `--workers` from
   `WEB_CONCURRENCY` when the flag is omitted — but the Dockerfile passes an
   explicit `3`, which always wins. Whatever the dashboard says, this deploy
   runs 3 processes × 2 threads on a 512MB instance.
2. **The statement-upload request holds one database transaction open for its
   entire (possibly multi-minute) duration, on a transaction pooler built for
   the opposite pattern (OPS-002).** `TenantContextMiddleware` wraps the whole
   request — including the synchronous, in-request LLM classification loop — in
   a single `transaction.atomic()`. A slow upload doesn't just block one gunicorn
   thread; it pins one Supabase pooler connection for minutes, and a handful of
   concurrent uploads can exhaust the pool.
3. **`manage.py check --deploy` never actually runs in this deployment
   (OPS-003).** Neither the Dockerfile's `CMD` nor CI's
   `check --fail-level WARNING` step passes `--deploy`, so the checks that would
   catch a missing `CACHE_URL` (per-process login lockouts, OPS-006) or
   mismatched DB roles never fire anywhere in the pipeline — confirmed by
   running it locally just now.

Also worth a look early, not quite top-three: the Vercel-served HTML shell
carries none of Django's security headers (OPS-001), and `TRUSTED_PROXY_COUNT`
can't be correct for both the Vercel-proxied path and direct-to-Render traffic
at once (OPS-012).

What's confirmed working, so nobody re-litigates it: `FRONTEND_URL` is **not** a
placeholder — `GET /` on Render 302s to `https://autoca-jade.vercel.app` (OPS-010).
The CSRF cookie round-trips correctly through the Vercel rewrite
(`Set-Cookie: csrftoken=...; SameSite=Strict; Secure` seen on `/auth/csrf/` fetched
from the Vercel origin). `.env` is properly gitignored and — checked across all of
git history, not just the current tree — only `.env.example` was ever committed;
nothing to rotate on that account. Vercel returns `403` for any `*.map` request
platform-wide, so `sourcemap: true` in `web/vite.config.ts` is not actually
exposing source to a visitor today (Vercel's own behaviour, not this app's —
worth re-checking if the static host ever changes). The Supabase pooling settings
themselves are right for transaction-pooling mode (`CONN_MAX_AGE=0`, server-side
cursors off, `SET LOCAL` rather than `SET` in the tenancy middleware) — OPS-002 is
about how long a transaction is held, not how it's configured. Distinct DB roles
and RLS-bypass checks (`core.E010/E011/E013`) all pass clean, including when
re-run locally against `config.settings.prod`.

---

### OPS-001 · major · The SPA's own HTML/JS ship with no CSP, no frame protection, no `nosniff`
- **Role / area:** `web/vercel.json`, every page the SPA serves
- **Repro:** `curl -sS -D - https://autoca-jade.vercel.app/` →
  `Strict-Transport-Security` only. Compare `curl -sS -D -
  https://autoca-jade.vercel.app/healthz` (rewritten to Render) → full CSP,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Cross-Origin-Opener-Policy`, `Permissions-Policy`, all present. `web/vercel.json`
  has a `rewrites` array and nothing else — no `headers` block.
- **Expected:** the page that loads and runs the application's own JavaScript is
  at least as hardened as the JSON endpoints it calls.
- **Actual:** it isn't hardened at all beyond what Vercel adds by default (HSTS).
  `django.middleware.clickjacking` and `core.middleware.headers.
  SecurityHeadersMiddleware` only ever see requests that reach Django — the SPA
  shell (`index.html`, the built JS/CSS) is served directly by Vercel's static
  host and never touches Django, so those middlewares are structurally unable to
  protect it. `SESSION_COOKIE_SAMESITE = "Strict"` does mean a framed copy of the
  app on a foreign top-level site won't carry the session cookie — so this isn't
  a clickjacking hole on its own — but with no CSP at all on the shell, an XSS
  bug anywhere in the SPA (a dependency, a rendered field) has no backstop:
  nothing stops it loading a remote script, exfiltrating via `fetch` to an
  arbitrary origin, or framing/embedding content Django would otherwise refuse.
- **Evidence:** curl output above (`web/vercel.json` reproduced: only the four
  `rewrites` entries, no `headers` key).
- **Suggested direction:** add a `headers` block to `web/vercel.json` mirroring
  `_CSP_STRICT` from `config/settings/base.py`, plus `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`. Before
  setting `script-src 'self'`, check the built `index.html` and Vite output for
  any inline `<script>` or inline event handler — Vite's default output shouldn't
  have any, but it's worth confirming rather than assuming, since a strict CSP
  landing on a page with an inline script breaks the app outright.
- **Owner:** frontend-dev (the header values and confirming no inline script) —
  but `web/vercel.json` is on the list of files nobody touches without the
  orchestrator saying so (TEAM.md rule 8), so this needs the orchestrator's
  go-ahead before editing it.
- **Status:** open

### OPS-002 · blocker · A statement upload holds one DB transaction (and one pooler connection) open for its full, possibly multi-minute duration
- **Role / area:** `core/middleware/tenancy.py`, `core/jobs.py`,
  `classify/llm.py`, Supabase transaction pooler
- **Repro:** `TenantContextMiddleware.__call__` opens `with
  transaction.atomic():` and calls `return self.get_response(request)` from
  *inside* that block (`core/middleware/tenancy.py:78-109`) — the transaction
  isn't released until the whole downstream call chain, including the view,
  returns. `StatementUploadView.create()` (`api/views/banking.py:64-88`) calls
  `run_job(...)` synchronously; `run_job` (`core/jobs.py:66-116`) runs `work()`
  — `_ingest` → `ingest_statement` then `suggest_unresolved` — inline, in the
  same request. `suggest_unresolved` (`classify/llm.py:238-262`) loops
  sequentially over batches of `LLM_BATCH_SIZE=25` rows, each batch a blocking
  Groq call with up to `LLM_TIMEOUT_SECONDS=30` (default) before it gives up on
  that batch. `core/jobs.py`'s own `with transaction.atomic():` around `work()`
  is a Django *savepoint*, not a new connection — Django nests atomic blocks —
  so nothing here releases the outer transaction or the connection early.

  (Checked, so as not to repeat a wrong theory: gunicorn's `--threads 2` promotes
  it to the `gthread` worker class — confirmed from `gunicorn/config.py`'s
  `worker_class` property, which switches to `gthread` whenever `threads > 1` on
  a nominally `sync` worker. Per gunicorn's own `Timeout` setting docs, for
  non-sync workers `--timeout` "just means that the worker process is still
  communicating and is not tied to the length of time required to handle a
  single request" — so a slow request is **not** what trips gunicorn's 120s
  timeout the way a `sync` worker's would be. My first pass at this finding
  assumed it was; it doesn't hold up against gunicorn's own source, so the
  mechanism below is the accurate one, not a killed-worker one.)
- **Expected:** a database transaction, especially against a transaction-mode
  pgbouncer pooler, is open for the length of a handful of queries — the pattern
  `DATABASE_IS_POOLED`/`CONN_MAX_AGE=0` is explicitly built for.
- **Actual:** the transaction is open for the length of an HTTP request that can
  legitimately run for minutes (multiple sequential model calls, each with its
  own 30s ceiling). For that whole time this request holds one pooler slot doing
  essentially nothing with it between LLM calls — not idle-in-transaction in the
  Postgres sense (the app is actively working), but not releasing the connection
  either. Supabase's free-tier pooler has a modest total slot count; two or three
  concurrent uploads (very plausible for a small firm, or one person double
  submitting after the Vercel-side timeout below makes it look like nothing
  happened) can plausibly exhaust it, at which point every *other* request —
  including ones that have nothing to do with uploads — starts failing to get a
  connection.

  Separately, and worth having in view at the same time: Vercel's rewrite proxy
  almost certainly gives up on the browser side well before this finishes (its
  timeout was not independently confirmed against production — I should not, and
  did not, upload a large PDF to prod to measure it, per rule 2). The browser
  sees a failure while Render keeps working underneath it with the transaction
  still open. If the user retries, there is no `idempotency_key` passed at this
  call site (`run_job(..., idempotency_key="")` is never set in
  `StatementUploadView.create`), so a retry starts a *second* full ingest+classify
  pass concurrently with the first, doubling the pooler pressure rather than
  reusing the in-flight job.
- **Evidence:** `core/middleware/tenancy.py:78-109`, `core/jobs.py:66-116`,
  `classify/llm.py:238-262`, `api/views/banking.py:64-88` (no
  `idempotency_key`), gunicorn's `worker_class`/`Timeout` source
  (`.venv/Lib/site-packages/gunicorn/config.py:105-121,779-798`).
- **Suggested direction:** the real fix is not holding a transaction across
  external calls at all — either move the LLM loop outside the request-scoped
  atomic block (commit the ingest, then classify in a separate transaction or
  genuinely out-of-request), or shrink what's inside the middleware's atomic
  block to just the tenant-context bookkeeping, opening a fresh transaction per
  unit of work in the view instead. Shorter term: give the upload endpoint a
  real `idempotency_key` (e.g. a hash of the client + file content, which
  `ingest_statement`'s own dedup logic suggests already exists somewhere nearby)
  so a retry after a client-side timeout reuses the job instead of doubling the
  load.
- **Owner:** backend-dev.
- **Status:** open

### OPS-003 · major · `manage.py check --deploy` is not run anywhere in the pipeline, so its own warnings (missing `CACHE_URL`, DB role mistakes) never fire
- **Role / area:** CI, Dockerfile, `core/checks.py`
- **Repro:** `.github/workflows/ci.yml`'s "Django system checks" step runs
  `python manage.py check --fail-level WARNING` — no `--deploy`. The Dockerfile's
  `CMD` runs gunicorn directly, nothing else; only `compose.yaml`'s one-shot
  `migrate` service runs `check --deploy --database default`, and that service
  has no equivalent on Render (OPS-005). I ran it locally just now, safely (no
  `--database`, so `check_app_role_cannot_bypass_rls` — the one deploy check that
  touches the database — quietly no-ops on a `DatabaseError` rather than
  connecting) against `config.settings.prod`, and it surfaced
  `core.W014` — *"CACHES['default'] is in-memory. Login and MFA lockout counters
  are per process..."* — immediately, because the local `.env` has no
  `CACHE_URL` (confirmed by name only: `grep -o '^[A-Z_]*=' .env` does not list
  `CACHE_URL` at all).
- **Expected:** the one check written specifically to catch "you forgot
  `CACHE_URL` in production" (`core.checks.check_shared_cache_for_throttling`,
  tagged `deploy=True` for exactly this reason) actually runs somewhere in the
  path from a commit to a live deploy.
- **Actual:** it runs in nobody's pipeline. Whether Render's own `CACHE_URL` is
  set could not be checked from here (rule 3 — names only, and that's local
  `.env` names, not Render's), but if it isn't, or if a future change to Render's
  env accidentally drops it, nothing in CI or the container's own startup would
  notice — the app would just start enforcing login/MFA lockouts per-process
  (worse than "not enforced": three gunicorn workers is three separate counters,
  each also reset by a free-tier cold start, per OPS-006) with no warning
  anywhere.
- **Evidence:** `.github/workflows/ci.yml`'s "Django system checks" step;
  `Dockerfile`'s `CMD`; local `check --deploy` output today (`core.W014`);
  `core/checks.py:198-216`.
- **Suggested direction:** add `--deploy` to CI's system-check step (it already
  has a database available in that job, from the `services: postgres:` block, so
  the DB-touching check gets exercised too, not just skipped as it was locally
  just now); separately, have the Dockerfile `CMD` (or an entrypoint script) run
  `python manage.py check --deploy` once before starting gunicorn, so a
  misconfigured Render env fails the deploy loudly instead of degrading
  silently.
- **Owner:** backend-dev.
- **Status:** open

### OPS-004 · major · Celery/Upstash is wired but nothing enqueues through it, and there is no worker to run it if something did
- **Role / area:** `integrations/queue/celery_redis.py`, Render services
- **Repro:** `grep -rn "\.enqueue(\|get_queue("` across the repo outside
  `integrations/` and `config/settings/test.py` returns nothing. Statement
  processing runs inline (OPS-002), not through the queue. No `render.yaml` and
  no worker process defined anywhere in the repo — Render, as far as the code
  shows, runs one service: the web dyno.
- **Expected:** either the queue isn't provisioned until something uses it, or a
  worker exists to drain it once something does.
- **Actual:** benign today — nothing is silently lost, because nothing is
  enqueued. But `QUEUE_BACKEND` defaults to the Celery/Redis adapter, and
  `core/jobs.py`'s own module docstring says plainly this is the intended future
  ("today it happens inline... when Celery workers land it happens on a worker,
  and nothing above this module changes"). The day a call site does
  `get_queue().enqueue(...)`, those tasks queue in Upstash and are never
  consumed, with no error anywhere — exactly the kind of change that passes
  review clean and then does nothing in production. Downgraded from what a first
  pass might call this: it is not a live bug, it's a trap for the next person who
  wires something onto the queue believing a worker will pick it up.
- **Evidence:** as above; `core/jobs.py:1-10`; `docs/ARCHITECTURE.md:54`.
- **Suggested direction:** a one-line comment at `get_queue()`'s definition
  pointing at this finding costs nothing; a `core.checks` deploy check that fails
  if the Celery adapter is selected with no recent worker heartbeat is the
  sturdier version. Note the trade-off either way: an actual always-on Celery
  worker is a second Render instance-month, and even an idle one polling Upstash
  spends part of the 500K/month command quota just checking for work — not
  something to add casually.
- **Owner:** backend-dev (the guard or the comment); user (decide, when the day
  comes, whether to provision a worker service).
- **Status:** open

### OPS-005 · major · No automated migration step for Render; a shipped migration and a deployed release can race
- **Role / area:** deploy process, `Dockerfile`, `compose.yaml`
- **Repro:** `compose.yaml` runs a one-shot `migrate` service before `web` starts
  (`depends_on: migrate: condition: service_completed_successfully`). The
  Dockerfile's own comment: migrations run "once, by the migrate service in
  compose (or the release phase of a PaaS) — never from every web replica at
  boot." TEAM.md rule 5 says the same thing about this specific deployment:
  "Render has no pre-deploy step."
- **Expected:** a migration lands in the schema before the code that depends on
  it starts serving traffic, deterministically, every time.
- **Actual:** `main` auto-deploys to Render on push. If a migration and the code
  that needs it ship in the same push, the new container can start serving
  requests against the old schema until a human runs `manage.py migrate
  --database=owner` by hand — a window bounded only by how fast a person acts.
- **Evidence:** `Dockerfile:32-33`, `compose.yaml:41-58`, TEAM.md rule 5.
- **Suggested direction:** without paying for Render's paid-tier Pre-Deploy
  Command, the safest mechanism is process: write every migration additive-only
  (new nullable column, new table, backfill later — never a rename/drop in the
  same step as code that assumes it's already gone; classic expand/contract), and
  have the developer who reports a `MIGRATION` finding hold the push until the
  user has run it against `DATABASE_OWNER_URL` and confirmed it clean — which is
  already what TEAM.md rule 5 asks for. This finding is flagging that it's a
  manual discipline with no safety net under it, not that the discipline is
  missing. If billing ever moves off free tier, Render's native Pre-Deploy
  Command is the thing to switch to.
- **Owner:** user (the manual migrate step, and any future Pre-Deploy Command);
  backend-dev (additive-first migrations so a missed window is never actually
  unsafe).
- **Status:** open

### OPS-006 · major · `CACHE_URL`, worker count, and the free-tier sleep compound against the login/MFA lockout
- **Role / area:** `core/throttle.py`, `CACHES['default']`, Render free-tier sleep
- **Repro:** `config/settings/base.py:382-388` falls back to `LocMemCache` when
  `CACHE_URL` is unset. Local `.env` has no `CACHE_URL` (name-only check, per
  rule 3); whether Render's does could not be checked, but this is exactly what
  `core.checks.check_shared_cache_for_throttling` exists to catch — and, per
  OPS-003, that check never actually runs against the live config.
- **Expected:** every failed login/MFA/invite attempt counts against the same
  shared counter, everywhere, until the window or the lockout ends.
- **Actual, if `CACHE_URL` is unset on Render:** with the Dockerfile's
  `--workers 3` (OPS-011: always 3, regardless of `WEB_CONCURRENCY`), each
  gunicorn *process* has its own in-memory cache, so an attacker gets roughly 3x
  the configured attempts before any one process locks them out.
  Worse, the free tier sleeps after 15 minutes idle (`docs/ARCHITECTURE.md:795`)
  — every cold start is a fresh process with an empty cache, so a lockout does
  not even need to be waited out; it needs the app to go idle once, which happens
  on its own between real users' sessions on a low-traffic deployment. This
  compounds with OPS-012 (`TRUSTED_PROXY_COUNT`/`client_ip()`) since the
  address-keyed half of the throttle is only as good as the address it's keyed on.
- **Evidence:** `config/settings/base.py:382-400`, `core/checks.py:198-216`,
  `docs/ARCHITECTURE.md:795`; local `.env` names list has no `CACHE_URL`.
- **Suggested direction:** confirm `CACHE_URL` is set on Render to the Upstash
  instance (it's a different logical use of the same free Redis the Celery
  broker URL points at — a different DB index or key prefix keeps the two from
  colliding; Upstash's free tier does support numbered databases, but if that
  turns out not to be reachable, `CACHE_URL`'s docs support a `KEY_PREFIX` as a
  fallback). This is cheap for Upstash's quota either way — the cache is only
  touched on login, MFA and invite attempts, not on every request.
- **Owner:** user (confirm/set `CACHE_URL` in the Render dashboard — this is a
  value only they can see); backend-dev (once OPS-003 lands, the deploy check
  makes this self-enforcing going forward).
- **Status:** open

### OPS-007 · minor · No error tracking or uptime alerting anywhere in the stack; logs aren't correlated by request id
- **Role / area:** observability
- **Repro:** `grep -rn "sentry\|SENTRY\|Rollbar\|Bugsnag"` across the repo:
  nothing. `LOGGING`'s formatter (`config/settings/base.py:654-677`) is
  `"%(asctime)s %(levelname)s %(name)s %(message)s"` — no request id field —
  even though `AuditMiddleware` computes one and echoes it back as
  `X-Request-ID` on every response (confirmed present on every curl done this
  round). No scheduled uptime check anywhere (`.github/workflows/` has only
  `ci.yml`, triggered on `push`/`pull_request`, no `schedule:`).
- **Expected:** an unhandled exception surfaces to a person without them going
  looking for it, a stuck/OOM/asleep instance is visible before a client notices
  first, and a log line from a specific failed request can be found by the id
  the response already carries.
- **Actual:** `core/jobs.py` does log unexpected exceptions with a traceback and
  points the user's error message at "job {id}" — genuinely good design for
  support to follow up on — but the traceback only lives in Render's log
  viewer, which isn't searchable across days on the free tier, isn't correlated
  to `X-Request-ID` by the log format itself, and nobody is watching it live.
- **Evidence:** as above.
- **Suggested direction:** a free-tier error tracker (Sentry's free tier is
  generous enough here) wired through `LOGGING`, a free uptime pinger
  (UptimeRobot / Better Uptime / a scheduled GitHub Action) hitting `/healthz`
  on both origins, and adding `request_id` to the log formatter via a
  `logging.Filter` (the audit middleware already computes the value; a
  `contextvar` or a `LogRecord` filter would make it available everywhere, not
  just the audit table).
- **Owner:** user (accounts: Sentry DSN, uptime pinger); backend-dev (wire the
  DSN and the log filter once an account exists).
- **Status:** open

### OPS-008 · minor · `scripts/supabase_keepalive.py` exists but nothing in the repo schedules it; Supabase backups/restore and both platforms' rollback are unverified
- **Role / area:** Supabase free-tier pause avoidance, backups, rollback
- **Repro:** the script's own docstring says "run it on a schedule (GitHub
  Actions cron, or Render's free cron)". `.github/workflows/` has no
  `schedule:` trigger anywhere, and there's no `render.yaml` cron definition in
  the repo — it may already be configured directly in a dashboard, which
  wouldn't show up here either way.
- **Expected:** the keepalive genuinely runs every couple of days unattended;
  Supabase's free-tier backup/restore story and each platform's rollback
  mechanism are understood before they're needed under pressure.
- **Actual:** unverified from the repo. Also out of reach from here: Supabase's
  free tier's actual backup retention (point-in-time recovery is a paid add-on
  on Supabase; the free tier's daily-backup retention window is worth confirming
  in the dashboard rather than assumed), and what "rollback" means concretely on
  each host — Render's is a redeploy of a previous image/commit from its
  dashboard; Vercel's is "promote a previous deployment" from its dashboard;
  neither one rolls back a migration that already ran, which is exactly why
  OPS-005's additive-migration discipline matters.
- **Evidence:** `scripts/supabase_keepalive.py:1-10`; absence of a scheduled
  workflow.
- **Suggested direction:** if the keepalive isn't already a Render Cron Job or a
  scheduled GitHub Action, add one. Separately, spend five minutes in the
  Supabase dashboard (Database → Backups) confirming what's actually retained on
  the free tier, and write down, once, what clicking "rollback" does on Render
  and on Vercel — not now, but before the first time it's needed for real.
- **Owner:** user (dashboard work on all three counts).
- **Status:** open

### OPS-009 · minor · Cold-start and slow-upload UX: the SPA has no client-side timeout or "this can take a minute" messaging
- **Role / area:** `web/src/api/client.ts`, first load after Render's free-tier
  sleep, statement upload
- **Repro:** `web/src/api/client.ts`'s `send`/`apiFetch` path (and the
  hand-typed `raw.*` helpers) construct a plain `fetch` `Request` with no
  `AbortSignal.timeout(...)` and no retry beyond the one CSRF-refresh-and-retry
  case. Nothing here or in the initial CSRF/session bootstrap distinguishes "the
  server is slow to wake up" from any other kind of failure.
- **Expected:** a user who opens the app right after 15 minutes of no traffic
  (30-60s cold start, per `docs/ARCHITECTURE.md:795`) sees something that
  explains the wait, and a statement upload that's genuinely going to take a
  while (OPS-002) says so rather than looking identical to a hang.
- **Actual:** whatever TanStack Query's default loading state renders — not
  independently confirmed against the built UI this round (ux-critic's lane),
  but nothing in the transport layer itself sets up a threshold-based message or
  a client-side abort.
- **Evidence:** `web/src/api/client.ts:1-160` (no `AbortController`/timeout
  anywhere in the file).
- **Suggested direction:** a "waking up the server, this can take up to a
  minute" message once a request has been pending past a few seconds (not a
  hard client-side timeout — that would just add a fourth timeout to the
  already-uncoordinated set in OPS-002) would cost little and answer the most
  likely support question from a real user.
- **Owner:** frontend-dev.
- **Status:** open

### OPS-011 · blocker · Dockerfile's explicit `--workers 3` overrides `WEB_CONCURRENCY`; the deployed concurrency is whatever the image says, not the dashboard
- **Role / area:** `Dockerfile`, Render web service memory (512MB)
- **Repro:** `Dockerfile`'s `CMD`: `gunicorn ... --workers 3 --threads 2 ...`.
  Gunicorn's own `Workers` setting (`.venv/Lib/site-packages/gunicorn/
  config.py:642-660`) defaults to `int(os.environ.get("WEB_CONCURRENCY", 1))` —
  but only when `--workers`/`-w` isn't passed on the command line. It is passed
  here, explicitly, as `3`, which always wins over the environment variable
  regardless of what Render's dashboard has it set to.
- **Expected:** the operator can size worker count for the instance's RAM from
  Render's dashboard, and the two agree.
- **Actual:** they cannot. Whatever `WEB_CONCURRENCY` is set to, this image runs
  3 gunicorn processes; `--threads 2` promotes each to the `gthread` worker
  class (confirmed from `worker_class`'s property logic, same file, lines
  105-121), so it's 3 processes × 2 threads = up to 6 requests handled at once,
  each on a full Python/Django process (Django, DRF, pdfplumber, the Groq
  client, cryptography) — on a 512MB instance. Separately worth knowing: the
  Render start command actually run is not fully confirmed from the repo either
  — `core/checks.py`'s own docstring says of `check --deploy`, "CI runs them,
  and so does the Render start command," which implies Render may have a Docker
  Command override configured in its dashboard rather than using the
  Dockerfile's `CMD` verbatim. That override, if it exists, is invisible from
  here (rule 3/dashboard-only) and could mean the actual running command differs
  from what's in this repo in either direction.
- **Evidence:** `Dockerfile:34-39`; gunicorn's `Workers`/`worker_class` source as
  above; `core/checks.py:8-9`; `docs/ARCHITECTURE.md:795` ("Render free: 512MB
  RAM").
- **Suggested direction:** delete the explicit `--workers 3` from the Dockerfile
  `CMD` entirely and let gunicorn read `WEB_CONCURRENCY` itself (defaulting to
  `1`, which is the right default for a 512MB instance with threads doing the
  concurrency work instead of processes) — no new config file needed, since
  gunicorn already does this natively. Once that's in, confirm in the Render
  dashboard whether a Docker Command override is set (Render → the service →
  Settings → Docker Command) and reconcile it with the Dockerfile so there's one
  source of truth, not two that can silently disagree.
- **Owner:** backend-dev (the Dockerfile change); user (check/clear any Docker
  Command override in the Render dashboard, and set `WEB_CONCURRENCY` with the
  512MB ceiling in mind once the flag no longer overrides it).
- **Status:** open

### OPS-012 · major · `TRUSTED_PROXY_COUNT` can't be correct for both the Vercel-proxied path and direct-to-Render traffic at once
- **Role / area:** `core/http.py: client_ip()`, `core/throttle.py`,
  `core/middleware/audit.py`, prod `TRUSTED_PROXY_COUNT`
- **Repro:** `curl -H "Host: evil.example.com" https://autoca-juie.onrender.com/healthz`
  → `403` from Cloudflare (`Server: cloudflare`, `CF-RAY` present) before Django
  is ever reached — confirms Render's own `*.onrender.com` domain is already
  behind Cloudflare. Real web traffic additionally goes browser → Vercel edge
  (which performs the external rewrite as a fresh *outbound* request of its
  own) → that same Cloudflare front door → Render's internal router → gunicorn.
  `config/settings/prod.py:36` defaults `TRUSTED_PROXY_COUNT` to `1`;
  `core/http.py:21-40` takes the `N`th-from-the-right entry of
  `X-Forwarded-For` for exactly that many trusted hops. One global integer
  cannot be right for a request that arrived via the Vercel rewrite (one extra
  hop, prepended before Cloudflare ever sees it) and a request that hits
  `autoca-juie.onrender.com` directly (no Vercel hop at all — true of the admin,
  the API docs, and anyone who calls Render's own domain instead of going
  through the SPA).
- **Expected:** `client_ip()` resolves to the real browser's address on the path
  that matters most — the one nearly all real traffic takes, through the SPA and
  the Vercel rewrite — since that address feeds both the audit log's
  `ip_address` column and the address-keyed half of the login/MFA lockout
  (`core/throttle.py`).
- **Actual:** unverified in either direction from outside — Django never echoes
  the resolved address back on a passive `GET`, and signing in to check it from
  the inside is against rule 2. If the count is off by even one hop on the
  Vercel path, `client_ip()` either returns a constant intermediate proxy
  address for every visitor (which would put every browser's login attempts
  into the *same* address-keyed lockout bucket — one person mistyping a
  password enough times locks out everyone signing in through the SPA for that
  window) or resolves to some other wrong value further down the chain. Either
  way the audit trail's "from where" is not trustworthy for the path real users
  take, which is the one place it matters most.
- **Evidence:** `core/http.py:21-40`, `core/throttle.py` (`_key` hashes whatever
  `client_ip()` returns), `config/settings/prod.py:36`; Cloudflare headers on
  direct-to-Render curls as above.
- **Suggested direction:** this needs the actual chain measured, not guessed.
  The cleanest way is a short-lived, admin-only debug endpoint (behind the
  existing platform-admin auth, removed after use) that logs or returns the raw
  `X-Forwarded-For` it received and what `client_ip()` resolved from it — hit
  once through the Vercel URL and once directly against Render, by someone
  signed in, and set `TRUSTED_PROXY_COUNT` from what's actually observed rather
  than assumed. Do not guess a number and move on; the two paths may end up
  needing to be told apart rather than sharing one setting (e.g. by trusting a
  header only Cloudflare could have set, if Render's Cloudflare front door can
  be confirmed to strip/rewrite `X-Forwarded-For` from what it receives rather
  than blindly appending to it — that distinction has to be verified against
  Render's actual behaviour, not assumed from how Cloudflare usually works).
- **Owner:** backend-dev (the verification endpoint and the eventual fix); user
  (run the one-off check against the live dashboards, since only they can safely
  sign in to production to do it).
- **Status:** open

### OPS-010 · cleared · `FRONTEND_URL` is not a placeholder
- **Role / area:** CSRF trusted origin, invitation links
- **Repro:** `curl -sS -D - https://autoca-juie.onrender.com/` → `302 Found`,
  `location: https://autoca-jade.vercel.app`. A local/placeholder value here
  would have tripped `core.checks.check_frontend_url_is_not_local_in_production`
  (`core/checks.py:39-54`, `core.W016`) and shown up as a redirect to
  `localhost` — it doesn't.
- **Evidence:** curl output above.
- **Suggested direction:** none — noted only so this round's named known-risk
  doesn't get re-checked from scratch.
- **Owner:** n/a.
- **Status:** open (informational; nothing for a developer to change)

---

Also noticed, not written up as full findings: `MAX_STATEMENT_UPLOAD_BYTES=25MB`
against Vercel's request body-size behaviour for an externally-rewritten POST was
not verifiable without sending a real large PDF through production, which rule 2
and rule 1 (only an orchestrator-approved real statement, named) both forbid doing
unprompted this round — flag for whoever gets that approval to watch for a
Vercel-level rejection (which would look like a generic gateway error, not the
API's own `422` with a `code`) rather than assume the 25MB ceiling is what a real
upload will hit first. A request through the Vercel origin with no session
(`/api/me/`) correctly answers `401` rather than leaking anything about whether a
resource exists — the permission boundary held up on every passive check made.

Findings this file: 2 blocker (OPS-002, OPS-011), 6 major (OPS-001, OPS-003,
OPS-004, OPS-005, OPS-006, OPS-012), 3 minor (OPS-007, OPS-008, OPS-009),
1 informational (OPS-010).
