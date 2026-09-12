# AutoCA

Multi-tenant automation platform for CA firms. One deployment serves many firms;
every firm's data is isolated from every other firm's by PostgreSQL row-level
security, on a database role that has no way to turn it off.

**Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before writing code here.**
Two rules govern everything: external services only via adapters in
`integrations/`, and tenant isolation enforced by Postgres rather than by
application logic.

## Status

Phase 1 works end to end: a bank statement PDF goes in, and approved, permanent
journal entries come out -- with Tally import XML and the standard reports on
top of them.

```
statement.pdf -> registered, hashed, deduplicated
              -> parsed and proved against its own balances
              -> continuity checked against the previous statement
              -> narration read for channel, payee and reference
              -> rules applied, each with a confidence; the rest queued
              -> a person reviews; every decision teaches a rule
              -> a senior CA approves -> immutable journal entry
              -> Tally XML, Trial Balance, P&L, Balance Sheet
              -> month-end: does the bank ledger match the bank?
```

Verified against a real 3-page Axis savings statement. The 54 rows parse and tie
to the paisa, and the posted FY2025-26 bank ledger totals -- ₹54,20,836.96 debit
and ₹44,95,705.00 credit -- match the accountant's own Tally ledger for the same
account exactly.

Nothing reaches a client's books without a senior CA approving it, and nothing
approved can be altered afterwards: the journal tables have no UPDATE or DELETE
grant and triggers that raise. Corrections are new entries that reverse and
replace, leaving the original visible.

Axis is the only statement format implemented. GST reconciliation is Phase 2 and
`gst/` is still an empty placeholder.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements/dev.txt

cp .env.example .env              # then fill it in
python -c "import secrets; print(secrets.token_urlsafe(64))"                    # DJANGO_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # KMS_LOCAL_MASTER_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                    # BLIND_INDEX_KEY
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

## Two conventions that are load-bearing

**Money is a whole number of paise**, in fields named `*_paise`. Never a float,
and never a `Decimal` -- see `core/money.py` for why the unit is in the field
name and what breaks when it is not.

**Account numbers and GSTINs are encrypted**, with a keyed blind index beside
them so rows can still be found and joined. `core/crypto.py` holds both halves.

## Running a statement through it

```bash
python manage.py ingest_statement \
    --firm <uuid> --client "Acme Traders" statement.pdf --export books.xml
```

The firm id is required: finding a client without knowing their firm would mean
reading `core_client` with no tenant context, which the database refuses to do.
`manage.py seed_demo` prints a firm id and its clients if you need one.

That ingests, classifies, and exports whatever has been **approved**. On a first
run nothing has, so the export is empty and says so — classification is a
suggestion, and only `ledger.approval.approve()` (senior CA or firm admin) turns
one into a book entry. Approve, then export again; the `REMOTEID` on each
voucher is stable, so Tally updates rather than duplicating.

## Verifying the guarantees

```bash
pytest core/tests/test_rls_isolation.py        # cross-tenant attack suite
pytest integrations/tests/test_adapter_swap.py # adapter boundary, envelope crypto
pytest banking/tests/test_balance_chain.py     # dropped rows, flipped columns, bad totals
pytest ledger/tests/test_approval.py           # immutability, attacked via ORM and raw SQL
pytest ledger/tests/test_tally_export.py       # double entry, Tally's inverted signs
pytest ledger/tests/test_reconciliation.py     # month end: books vs bank
pytest                                          # everything
```

Drop a real statement into `.devdata/samples/` (gitignored) and the opt-in test
in `integrations/tests/test_pdf_extraction.py` will parse it end to end. The
rest of the suite works from a captured, redacted extraction, so CI never needs
a client's bank statement to run.

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
documents/       every uploaded file, whatever kind, in one registry
banking/         statement parsing, ingestion, deduplication, continuity
  parsers/       one per bank format; each proves its own arithmetic
classify/        narration analysis, rules, vendors, the review queue
ledger/          approval, the immutable journal, Tally XML, reports
gst/             placeholder, no logic yet
scripts/         database role bootstrap, Supabase keepalive
```

Adding a bank format is one file in `banking/parsers/` plus an entry in
`PARSERS`. It does not need its own validation: `ParsedStatement` refuses to
exist unless the rows reproduce the statement's own opening balance, running
balances, printed totals and closing balance. Either it balances or it raises
with the row where the arithmetic first went wrong.

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
