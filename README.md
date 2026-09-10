# AutoCA

Multi-tenant automation platform for CA firms. One deployment serves many firms;
every firm's data is isolated from every other firm's by PostgreSQL row-level
security, on a database role that has no way to turn it off.

**Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before writing code here.**
Two rules govern everything: external services only via adapters in
`integrations/`, and tenant isolation enforced by Postgres rather than by
application logic.

## Status

Scaffold, tenant isolation, and guardrails. Document parsing, classification,
the ledger, and GST reconciliation are later phases; their apps exist as empty
placeholders.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements/dev.txt

cp .env.example .env              # then fill it in
python -c "import secrets; print(secrets.token_urlsafe(64))"                    # DJANGO_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # KMS_LOCAL_MASTER_KEY
```

Then, in the Supabase SQL editor, run `scripts/bootstrap_db_roles.sql` (change
both passwords first) to create the owner and application roles. This step is not
optional — running the app as Supabase's `postgres` role would silently disable
tenant isolation, and `manage.py check` will tell you so.

```bash
python manage.py migrate --database=owner
python manage.py grant_app_role --database=owner
python manage.py check --deploy --database default
python manage.py rls_status
python manage.py runserver
```

## Verifying the security guarantees

```bash
pytest core/tests/test_rls_isolation.py       # cross-tenant attack suite
pytest integrations/tests/test_adapter_swap.py # adapter boundary, envelope crypto
pytest                                         # everything
```

The isolation suite is a release gate in CI and requires a real PostgreSQL —
there is no SQLite fallback, because SQLite cannot express RLS and would let
un-isolated code pass.

## Layout

```
config/          settings (base / dev / prod / test), urls, celery
core/            tenancy, users, RBAC, audit, crypto call sites
  db/            RLS policy generation, session context, introspection
  middleware/    mfa -> tenancy -> audit, in that order
integrations/    every external service, behind an adapter interface
banking/ ledger/ gst/ classify/   placeholders, no logic yet
scripts/         database role bootstrap, Supabase keepalive
```

## Running the tests locally

The dev/test database is behind Supabase's connection pooler, which keeps a warm
connection to Django's scratch database and makes create/drop racy. Day to day:

```bash
pytest --reuse-db
```

After a schema change or an aborted run, reset it first:

```bash
.venv/Scripts/python.exe scripts/drop_test_db.py
pytest
```

CI needs neither — its Postgres service container has no pooler in front of it.

## Operational notes

- Render's free tier sleeps after 15 minutes; ping `/healthz` before a demo.
- Supabase free projects pause after 7 days idle. Run
  `scripts/supabase_keepalive.py` on a cron.
- `db.<ref>.supabase.co` may have no DNS record at all. Both roles connect through
  `aws-0-<region>.pooler.supabase.com`: migrations in session mode (5432), the app
  in transaction mode (6543) with `DATABASE_IS_POOLED=1`.
- Pooler usernames are `<role>.<project-ref>`, not the bare role name.
- After creating or altering a role, Supavisor caches the old credentials for
  ~60-90s. `password authentication failed` right after a change usually just
  means "wait a minute", not "wrong password".
- See `docs/ARCHITECTURE.md` for the PostgreSQL 16+ `GRANT ... WITH INHERIT TRUE`
  trap, which silently breaks the app role's privileges.
