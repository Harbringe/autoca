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

**Any bank.** There is no per-bank requirement: the generic parser infers which
column is which and proves the inference against the statement's own running
balance, so a format nobody anticipated either reads correctly or is refused.
A dedicated parser (Axis has one) is an optimisation, not a prerequisite.

There is a web application over all of it (`web/`, a separate static build):
sign in with a second factor, upload, review with the queue sorted by
confidence, place rows, approve, correct, read the reports, check month end,
download the Tally file. And there is a model tier behind the rules: rows no
rule can place are offered to a language model, which suggests a ledger with a
one-line reason -- never with enough confidence to be bulk-approved, and never
with anything identifying in the request.

GST reconciliation is Phase 2 and `gst/` is still an empty placeholder.

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
```

The backend serves the API and the platform admin; the web application
(`web/`, Node 24) is its own project. Run both:

```bash
python manage.py bootstrap_admin --email you@firm.test --firm "Your Firm" --demo
python manage.py runserver
cd web && npm ci && npm run dev
# open http://localhost:5173  -- sign in, scan the QR, you're in
```

The dev server proxies `/api` and `/auth` to Django, so the browser only ever
talks to one origin and the session cookie and CSRF flow are the real ones.

### With Docker

```bash
cp .env.example .env.compose        # fill in the secrets; set POSTGRES_PASSWORD,
                                    # AUTOCA_OWNER_PASSWORD, AUTOCA_WEB_PASSWORD too
docker compose up --build
# API and admin at http://localhost:8080 ; the web application is deployed separately (see web/README.md)
```

That is the whole topology the architecture asks for: nginx in front, one web
process, one Postgres with the two roles created at first start, one Redis for
the lockout counters. Migrations run once, as the owner role, before the web
process starts; the web process never holds the owner credentials.

### The model tier

Off by default. To turn it on with Groq:

```
LLM_BACKEND=integrations.llm.groq.GroqLLMAdapter
GROQ_API_KEY=gsk_...
```

What the model receives, and what it never does, is set out in
`classify/pseudonymise.py`. In one line: masked narrations, aliased vendors,
pseudonymised people, amount bands, and the client's ledger names -- and it
answers with one of those names, which is checked before anything is written.

## The API

`/api/v1/`, plain REST and JSON, documented at **`/api/docs/`** (Swagger UI) and
`/api/redoc/`. The schema at `/api/schema/` is generated from the code, so it
cannot drift from what the endpoints actually do.

```bash
python manage.py runserver
# then sign in at /auth/login/, pass the second factor, and open /api/docs/
```

Authentication is the session cookie the web login already issues, not a token.
A stolen JWT is valid until it expires and cannot be revoked, which is a poor
trade for a product holding client financial records. Everything behind
`/api/v1/` requires an authenticated, second-factor-verified session that
belongs to a firm; an API caller that has not passed MFA gets a JSON `403` with
a code, never a redirect to an HTML page.

Three conventions the whole API follows:

- **Money is an integer number of paise**, in `*_paise`, with a `*_display`
  twin already grouped the Indian way. Use the integer for arithmetic and the
  string for rendering. A JSON number with a decimal point becomes a float in a
  browser, which is precisely the error the backend exists to avoid.
- **Slow work returns `202` with a job.** Poll `/api/v1/jobs/{id}/` or subscribe
  to `/api/v1/jobs/{id}/events/` for server-sent events. Work runs inline today;
  the contract is in place so moving it to a worker changes nothing a client
  sees.
- **Errors carry a stable `code` and a readable `detail`.** The parser's own
  messages name the row and the figure that broke, and they are passed through
  rather than replaced. `422` means the document could not be read, `409` that
  the request conflicts with the current state, `403` a role boundary.

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

## Checking the work by hand

No Tally and no review screen yet, so everything is drivable and inspectable
from the command line.

```bash
# one page showing every row: as the bank printed it, as it was read,
# how it was classified and why, and the entry it became
python manage.py verify_statement --firm <uuid> --client "Acme" --out report.html

# the review queue, sorted by confidence
python manage.py review --firm <uuid> --client "Acme"
python manage.py review --firm <uuid> --client "Acme" --band JUDGEMENT

# place one row; the rule learned from it usually places several more
python manage.py review --firm <uuid> --client "Acme" \
    --place 1 --ledger "Office Expenses" --group INDIRECT_EXPENSE

# post them -- only a senior CA or firm admin may
python manage.py approve --firm <uuid> --client "Acme" --as ca@firm.test --band HIGH

# the books, and whether they agree with the bank
python manage.py books --firm <uuid> --client "Acme" --fy 2025 --reconcile 31-03-2026
```

`verify_statement` is the one to reach for when checking a new bank's format:
open it beside the original PDF and read down. The **Chain** column re-walks the
running balance independently of the parse, so a tick on every row means the
figures are the bank's own.

## Verifying the guarantees

```bash
pytest core/tests/test_rls_isolation.py        # cross-tenant attack suite
pytest integrations/tests/test_adapter_swap.py # adapter boundary, envelope crypto
pytest banking/tests/test_balance_chain.py     # dropped rows, flipped columns, bad totals
pytest banking/tests/test_generic_parser.py    # five bank layouts, no bank-specific code
pytest ledger/tests/test_approval.py           # immutability, attacked via ORM and raw SQL
pytest ledger/tests/test_tally_export.py       # double entry, Tally's inverted signs
pytest ledger/tests/test_reconciliation.py     # month end: books vs bank
pytest api/tests/test_api.py                   # the API, through the whole stack
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
api/              REST API and the generated OpenAPI schema
web/             the web application (React + Vite), a separate deployment
deploy/          nginx config and the compose role bootstrap
integrations/    every external service, behind an adapter interface
documents/       every uploaded file, whatever kind, in one registry
banking/         statement parsing, ingestion, deduplication, continuity
  parsers/       generic (any bank) plus dedicated ones; all prove their arithmetic
classify/        narration analysis, rules, vendors, the review queue
ledger/          approval, the immutable journal, Tally XML, reports
gst/             placeholder, no logic yet
scripts/         database role bootstrap, Supabase keepalive
```

Most banks need no code at all. `banking/parsers/generic.py` reads any ruled
transaction table by working out the column layout and checking it against the
running balance; `banking/tests/layouts.py` holds the arrangements it is proved
against (HDFC, ICICI, Kotak, SBI, and a header-less export). Add a new
arrangement there first -- a layout in that file and failing is a bug report, a
layout only in a customer's inbox is a support ticket.

A dedicated parser earns its place by being needed: when a layout defeats the
inference, or to pick up detail the generic path drops. It is one file plus an
entry in `DEDICATED_PARSERS`, and needs no validation of its own --
`ParsedStatement` refuses to exist unless the rows reproduce the statement's own
opening balance, running balances, printed totals and closing balance.

## Running the tests locally

```bash
pytest
```

The dev/test database is behind Supabase's connection pooler, which parks warm
server sessions on Django's scratch database and made every second run fail with
"already exists". `conftest.py` now clears a leftover scratch database at the
start of each run, and `pytest.ini` carries `--reuse-db` so Django does not
attempt the drop that could never succeed. The schema is still rebuilt from
migrations every run. CI needs none of this -- its Postgres service container
has no pooler in front of it.

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
