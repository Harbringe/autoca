# Architecture & guardrails

Scope of this phase: project scaffold, tenant isolation, and safety guardrails.
No document parsing, no classification, no ledger, no GST. Those are later
prompts, and the placeholder apps (`banking/`, `ledger/`, `gst/`, `classify/`)
are empty on purpose.

---

## Rule 1 — every external service sits behind an adapter

Free hosting now, AWS at beta, with a swap that is a config change and one new
file. That single requirement drives the layout.

```
core/            tenancy, users, RBAC, audit, crypto call sites
integrations/    ALL external service calls, behind adapter interfaces
  storage/       dev: Cloudflare R2      beta: AWS S3
  ocr/           dev: stub (see below)   beta: Azure DI S0 / Document AI
  queue/         dev: Upstash Redis      beta: AWS SQS / ElastiCache
  kms/           dev: local Fernet       beta: AWS KMS
  llm/           not wired this phase
banking/ ledger/ gst/ classify/   structure only
```

**Nothing outside `integrations/` imports a vendor SDK.** Not `boto3`, not a
Supabase client, not `redis`. `integrations/tests/test_adapter_swap.py` walks the
AST of every file in `core/`, `banking/`, `ledger/`, `gst/`, `classify/` and
`config/` and fails CI on any such import. This is the rule most likely to rot
quietly, which is why it is the one with a static check behind it.

Business logic calls `get_storage()`, `get_kms()`, `get_queue()`. It never
learns which vendor answered.

### What a swap actually costs

| Layer | Dev | Beta | Cost of the move |
|---|---|---|---|
| Storage | Cloudflare R2 | AWS S3 | 3 env vars. R2 and S3 share one implementation class, asserted by a test. |
| Database | Supabase Postgres | AWS RDS | Connection string. Same SQL, same RLS policies, same pgvector — Supabase is vanilla Postgres. The cleanest swap in the stack. |
| Queue | Upstash Redis | SQS / ElastiCache | One adapter file (`integrations/queue/sqs.py`, stubbed). |
| KMS | local Fernet | AWS KMS | One adapter file. The envelope format lives in the base class and does not change, so existing ciphertext stays readable after a one-time data-key rewrap. |
| Frontend | Vercel | Vercel | No move planned. |
| Backend | Render free | AWS ECS/EC2 | Standard Django deploy. |

---

## Rule 2 — tenant isolation is enforced by Postgres, not by Python

The application connects on a role that **cannot** see another firm's rows. Not
"does not"; cannot. Every firm-scoped table carries:

```sql
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
ALTER TABLE t FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON t
    FOR ALL TO autoca_app
    USING      (firm_id = app.current_firm_id())
    WITH CHECK (firm_id = app.current_firm_id());
```

Three things make that real rather than decorative.

**Two database roles.** `autoca_owner` owns the schema and runs migrations.
`autoca_web` serves every request and is `NOSUPERUSER NOBYPASSRLS`, owns nothing,
and holds only DML grants. All three RLS escape hatches — superuser, `BYPASSRLS`,
and owner-without-`FORCE` — are closed. `core/checks.py` turns each into a
deploy-time system-check failure, so a misconfiguration cannot reach production
quietly. Set up with `scripts/bootstrap_db_roles.sql`.

**`FORCE`, not just `ENABLE`.** Without `FORCE` the owner is exempt from its own
policies. We split the roles *and* force the policies — the belt is what saves
you the day someone runs the app as the owner by accident.

**Transaction-scoped context.** `TenantContextMiddleware` opens a transaction and
issues `set_config('app.firm_id', <uuid>, is_local => true)` — the parameterised
equivalent of `SET LOCAL`. Transaction-scoped is mandatory under Supabase's
transaction pooler, where the same backend connection is handed to a different
tenant the moment ours commits. A session-scoped `SET` would leak one firm's
context into another firm's request. `test_context_does_not_survive_its_transaction`
is the regression test for the worst bug this codebase could have.

### Deny by default, loudly

An unset context does not return everything, and does not silently return
nothing either. `app.current_firm_id()` raises `insufficient_privilege`:

```
tenant context missing: app.firm_id is not set for this transaction
```

This is why the policy calls a function rather than inlining
`current_setting('app.firm_id')::uuid`. The inline form fails loudly the first
time, but `SET LOCAL` reverts a custom GUC to *defined and empty* at commit, and
`''::uuid` then produces a confusing cast error — while the obvious "fix",
`current_setting(..., true)`, returns NULL and matches zero rows. Silent. The
function collapses every path into one explicit exception.

### The one widened predicate, and why it is not a hole

Reading `core_firm_membership` is *how* a request discovers its firm, so it
cannot already require a firm context. Rather than granting a bypass — a hole
that would inevitably get reused for something else — membership has its own
predicate:

```sql
USING      (app.membership_visible(firm_id, user_id))
WITH CHECK (firm_id = app.current_firm_id())
```

A row is visible if it belongs to the active firm **or** to the authenticated
user (`app.user_id`, set one step earlier by the same middleware). With neither
context set it still raises. And `WITH CHECK` is unchanged, so discovering your
membership is never a route to granting yourself one.

### The isolation suite grows by itself

`core/tests/test_rls_isolation.py` has three layers:

1. **Structural** — enumerates `FirmScopedModel` subclasses and asserts each has
   `ENABLE`, `FORCE`, and a policy that actually consults the tenant context.
   Covers tables that do not exist yet.
2. **Coverage** — fails if a firm-scoped model has no row factory, which is what
   forces new tables into layer 3 instead of letting them slip past.
3. **Behavioural** — with firm A active, attempts to read, write, update and
   delete firm B's rows, and asserts none of it works.

Plus `test_no_model_smuggles_a_firm_fk_without_the_base_class`, which catches the
real trap: a model with a `firm` foreign key that skipped `FirmScopedModel`, so it
looks tenant-aware, gets no policy, and is invisible to any enumeration.

CI runs this against an **ephemeral Postgres service container**, not the shared
Supabase dev project — the gate must not be skippable because a free-tier project
was asleep. `test_connection_role_cannot_bypass_rls` asserts the CI role is not a
superuser, because if it were, every other assertion would pass vacuously.

---

## Rule 3 — encryption call sites are correct before there is anything to encrypt

`core/crypto.py` exposes `encrypt_for_firm` / `decrypt_for_firm`. The envelope
format and the AES-256-GCM data plane live in `integrations/kms/base.py` and are
identical for every backend; a KMS adapter only mints and unwraps data keys.

The encryption context — always including the firm id — is bound in as AES-GCM
additional authenticated data. A ciphertext belonging to firm A **cannot be
decrypted while firm B's context is active**, even if a bug hands the wrong blob
to the wrong tenant. That is a second, cryptographic isolation boundary beneath
the RLS one.

The dev adapter is a real envelope implementation whose master key happens to sit
in an env var. It is not key management: no rotation, no audit trail, no hardware
boundary. Adequate for development, unacceptable for client data.

Object storage gets its own boundary, because RLS does not reach it: every key is
built by `StorageAdapter.tenant_key()` as `firms/<firm_id>/...`, and
`verify_tenant_key()` refuses a key from the wrong firm.

---

## On OCR — read before wiring a vendor

**Do not use Azure Document Intelligence F0.** It allows 500 pages/month but
processes only the **first two pages of any document, dropping the rest without
raising an error**. Bank statements are rarely two pages. Testing against F0
produces results that are quietly incomplete and look successful — worse than a
hard failure, because nothing downstream can detect it. Google Document AI has no
equivalent standing free tier; what looks like one is expiring GCP trial credit.

OCR is the *fallback* path here anyway. Most bank statement PDFs are born-digital
and carry a real text layer, which should be extracted, not guessed at. So this
phase ships `StubOCRAdapter`, which **raises** rather than returning empty text.

The defence against this returning later is structural: `OCRResult` refuses to be
constructed when `pages_processed != page_count`. A truncating backend cannot
produce a plausible-looking result no matter who writes the adapter.

---

## Verifying the guarantees

```bash
python manage.py check --deploy --database default   # role privileges, middleware order
python manage.py rls_status                          # live ENABLE/FORCE/policy per table
pytest core/tests/test_rls_isolation.py              # cross-tenant attack suite
pytest integrations/tests/test_adapter_swap.py       # adapter boundary + envelope crypto
```

## Confirmed assumptions

- Multi-tenant SaaS: one deployment serving many firms. This is what the RLS
  design assumes throughout.
- One role per firm-user (`OWNER` / `STAFF`), no intra-firm per-client RBAC yet.
  The hook is `FirmMembership.scope_all_clients` plus `accessible_clients()`:
  adding per-client scoping is a migration and a queryset filter, not a refactor
  of every call site.

## Supabase gotchas, all four of which cost real time

These were hit during setup and are documented because each one *looks* like a
different problem than it is.

**The direct host may not exist.** `db.<ref>.supabase.co` resolved to no A and no
AAAA record on this project. Everything goes through the pooler:
`aws-0-<region>.pooler.supabase.com`, port 6543 for transaction mode and 5432 for
session mode. Migrations use session mode; the app uses transaction mode with
`DATABASE_IS_POOLED=1`.

**Pooler usernames are `<role>.<project-ref>`.** Supavisor routes by the username,
so a bare `autoca_web` fails. The server-side error still names the bare role,
which makes this confusing to read.

**Supavisor caches credentials for roughly 60-90 seconds.** After `CREATE ROLE` or
`ALTER ROLE ... PASSWORD`, connections fail with `password authentication failed`
until the cache turns over. It is indistinguishable from a wrong password. Wait
a minute and retry before changing anything.

**`GRANT role TO role` records its inherit option at grant time.** On PostgreSQL
16+, the option is copied from the member's `rolinherit` *when the grant runs*.
Granting to a `NOINHERIT` role and running `ALTER ROLE ... INHERIT` afterwards
does not fix the membership: `pg_auth_members` still shows the role as a member
while it inherits nothing, and every query fails with `permission denied for
table ...` rather than the tenant-context error you expect. Always
`GRANT ... WITH INHERIT TRUE`.

Related, and caught by the isolation suite rather than by inspection: **the test
role must be a member of `autoca_app`.** Policies are scoped `TO autoca_app`, and
a role outside that group has *no policy applied to it at all* — at which point
RLS denies everything by default, including a firm's writes to its own rows. The
symptom is a wall of failures that looks like broken isolation but is actually
isolation testing nothing.

## Verified on the live database

Connected as `autoca_web` against the development project, PostgreSQL 17.6:

```
connected as autoca_web  super=False bypassrls=False
OK  no-context read denied: tenant context missing: app.firm_id is not set for this transaction
OK  cannot disable RLS         (must be owner of table core_client)
OK  cannot un-force RLS        (must be owner of table core_client)
OK  cannot drop the policy     (must be owner of relation core_client)
OK  cannot grant itself BYPASSRLS
OK  scoped read succeeds
```

The application role cannot read without a tenant context, and cannot remove the
mechanism that stops it.

## Free-tier limits worth remembering

- **Render free**: 512MB RAM, spins down after 15 min idle, 30–60s cold start.
  Ping `/healthz` before a demo.
- **Supabase free**: 500MB, and **the project pauses after 7 days of inactivity**.
  `scripts/supabase_keepalive.py` on a cron prevents a bad Monday.
- **Upstash free**: 500K commands/month. Celery consumes commands while idle.
- **Cloudflare R2 free**: 10GB, 1M writes / 10M reads per month, zero egress.

Free-tier terms shift and several have added credit-card gates recently. Re-check
before committing to any of them.
