# Architecture & guardrails

Built so far: the scaffold and tenant isolation, then Phase 1 end to end — a
bank statement PDF in, approved permanent journal entries out, with Tally XML
and the standard reports on top. `gst/` adds GST reconciliation beside it: a
purchase register against GSTR-2B, one GSTIN and month at a time.

```
statement.pdf
  -> documents/             one registry for every uploaded file, hashed
  -> integrations/pdf/      text and table cells
  -> banking/parsers/       rows, proved against the statement's own balances
  -> banking/ingest         persisted, deduplicated, continuity checked
  -> classify/narration     channel, payee, reference pulled apart
  -> classify/engine        rules applied with a confidence; the rest queued
  -> [ a person reviews; every decision teaches a rule ]
  -> ledger/approval        a senior CA posts it -- immutable from here
  -> ledger/tally           Tally Prime import XML
  -> ledger/reports         Trial Balance, P&L, Balance Sheet
  -> ledger/reconciliation  month end: does the ledger match the bank?

register.xlsx + GSTR-2B.json
  -> gst/parsers            invoices, amounts exact in paise
  -> gst/matching           pure rules: match, mismatch kind, ITC (nothing fuzzy earns credit)
  -> gst/services           stored as staging; a person decides; a senior signs off
  -> gst/report             the screen and the Excel working paper, from one dictionary
```

One idea carries most of the weight: **make the wrong answer impossible to
construct, rather than checking for it afterwards.** A statement that does not
balance cannot become a `ParsedStatement`. A transaction with no ledger cannot
become an entry. A posted entry cannot be edited — not "is not edited"; cannot,
because the grant is revoked. None of these has a "validate this" call a caller
can forget.

The corollary, which is the shape of the whole product: **staging is mutable,
the ledger is not.** Everything up to approval can be corrected freely, because
a review workflow where nothing can be fixed is one nobody uses. Everything
after it is permanent, because Indian company law requires it to be.

---

## Rule 1 — every external service sits behind an adapter

Free hosting now, AWS at beta, with a swap that is a config change and one new
file. That single requirement drives the layout.

```
core/            tenancy, users, RBAC, audit, crypto call sites
integrations/    ALL external service calls, behind adapter interfaces
  storage/       dev: Cloudflare R2      beta: AWS S3
  pdf/           pdfplumber              (text layer + table cells)
  ocr/           dev: stub (see below)   beta: Azure DI S0 / Document AI
  queue/         dev: Upstash Redis      beta: AWS SQS / ElastiCache
  kms/           dev: local Fernet       beta: AWS KMS
  llm/           declared, not wired
api/             REST surface, permissions, error mapping, OpenAPI
documents/       one registry for every uploaded file
banking/         statement parsing, ingestion, deduplication, continuity
classify/        narration analysis, rules, vendors, the review queue
ledger/          approval, the immutable journal, Tally XML, reports
gst/             purchase register vs GSTR-2B, ITC, decisions, sign-off (removable add-on)
```

`pdf/` is behind the adapter boundary even though pdfplumber runs in-process
and is not a service. The rule is kept uniform on purpose: the day this moves
to PyMuPDF or a hosted extractor, the question "what else imports it?" should
have the same answer it has for boto3.

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

### The boundary RLS cannot see: two clients of one firm

Every policy above is keyed on `firm_id`, which is the right boundary for what it
defends against — one firm reading another's rows is impossible in the database
whatever the application does. Inside a firm it says nothing. Two clients of the
same firm are one tenant to PostgreSQL, and a CA firm's liability rests on their
books being separate.

That gap is not theoretical, and it is reachable in one step. A rule names a
ledger, a ledger belongs to exactly one client, and nothing in the schema made
the two agree. A rule carrying `client = NULL` — once described as "firm-wide" —
applied to every client in the firm while naming one client's ledger, so every
other client's matching transactions were placed into books that were not theirs.
It reaches posted journal lines, not just the review queue.

So the client boundary is enforced the same way the firm boundary is, in
PostgreSQL rather than in application code that the next `objects.create` can
walk past:

| Guarantee | Where |
| --- | --- |
| A rule belongs to exactly one client; there is no firm-wide rule | `classify_rule.client_id` NOT NULL |
| A rule's ledger is a ledger of that same client | `rule_ledger_same_client`, a composite FK on `(client_id, ledger_id)` |
| A rule's party is a party of that same client | `rule_vendor_same_client`, likewise |
| No journal line posts into another client's ledger | `journal_line_one_client`, a BEFORE INSERT trigger |

Three details that are the whole point rather than trivia:

* **`client_id` had to become NOT NULL.** A composite foreign key defaults to
  `MATCH SIMPLE`, under which a NULL in any referencing column satisfies the key
  trivially. Left nullable, a firm-wide rule would have walked straight through
  the constraint added to stop it.
* **The books get a trigger, not a key.** A composite key would need a
  `client_id` column on `ledger_journal_line`, and filling one in means an
  UPDATE against an append-only table that company law is the reason for. The
  table is insert-only, so `BEFORE INSERT` is exactly as strong.
* **Pre-existing posted lines are left alone.** A line already posted is part of
  the permanent record. The remedy for a wrong one is a superseding entry signed
  by a person, not a migration rewriting history.

`classify/tests/test_client_isolation.py` holds the behavioural half, including
two tests that bypass `full_clean` entirely to prove the database refuses the
write on its own. They call `SET CONSTRAINTS ALL IMMEDIATE` first: the composite
keys are deferred so that deleting a party, which Django handles by nulling the
reference mid-cascade, does not trip them, and a test transaction never commits.

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

## Rule 4 — a statement is proved, not trusted

A bank statement is one of the few documents in accounting that carries its own
proof. Every row prints the balance after it; the header and footer print the
balances either side of the lot. So a parse either reconstructs that chain
exactly or it is wrong, with no middle state where the output is "mostly right".

Every failure mode of PDF parsing is silent. A row lost at a page break, a debit
read out of the credit column, a continuation line mistaken for a row,
`1,00,000.00` losing a digit to a careless separator strip — none of these
raise, and all of them break the chain. So `ParsedStatement.__post_init__`
checks it and **refuses to construct** when it does not tie out, naming the row
where the arithmetic first diverged. The printed footer totals are checked too,
because they catch a compensating pair of errors that the chain alone would not.

There is no unvalidated `ParsedStatement` for a caller to hold, so no caller has
to remember to validate. Same shape as `OCRResult` refusing to exist when pages
went missing, and `PdfDocument` refusing when a backend returned fewer pages
than the document has.

The practical consequence is that a new bank's format can be accepted without a
human reading the output. Either it balances or it raises.

### Any bank, without a parser per bank

A parser per bank is exact and does not scale to the actual requirement: a firm
with thirty clients sees a dozen banks and a new one the week after you finish
the last. The architecture's answer was a generic table extractor with
"mandatory human column-confirmation". The implementation improves on that, and
the improvement comes free from Rule 4.

**Column roles are guessed, then proved.** The balance column is a running
total, so the difference between consecutive balances is exactly what that row
did to the account. A candidate mapping is correct if and only if the amounts it
picks out reproduce those differences on *every* row. Wrong mappings do not
almost-work -- they fail on the first pair and keep failing. So
`banking/parsers/columns.py` enumerates the plausible mappings and keeps the one
the arithmetic endorses.

That is a stronger check than a human confirming columns by eye, and it needs
nobody's attention. Between them the mappings cover every arrangement in Indian
retail banking: separate Withdrawal/Deposit columns in either order, Debit and
Credit with other columns interleaved, one Amount column with a Dr/Cr flag, and
tables with no header row at all.

Two things the arithmetic cannot vouch for, both handled explicitly:

- **The narration column** takes no part in the sums. It falls back to "the wide
  text column that is not a date", and the mapping records that it was a guess.
- **A serial-number column** parses as money -- `1, 2, 3` is a perfectly good
  rupee amount -- and would otherwise be tried as an amount column. Columns that
  are consecutive small integers are excluded up front.

`banking/tests/layouts.py` holds the layouts this is proved against. The
strongest test is that the generic parser reads the real 54-row Axis statement
identically to the dedicated Axis parser, row for row.

### Why the extractor returns cells rather than text

Flattened to a line, a row reads:

```
13-04-2025  Sweep/VO000000012345678/...  250.00  112500.00  318
```

and nothing in that string says whether the 250.00 was money in or money out.
Indian bank statements are ruled tables, so a table extractor recovers Debit and
Credit as separate cells and the direction is read rather than inferred. This is
also why `integrations/pdf/` exposes tables at all instead of just text.

---

## Rule 5 — classification keys on the payee, and learns

A narration is not free text; the bank builds it from a template.

```
UPI/P2M/100000000001/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD
^   ^   ^            ^                     ^      ^
|   |   reference    counterparty          remark counterparty's bank
|   person-to-merchant
channel
```

`classify/narration.py` pulls those apart before anything matches, and that
choice is what makes the feature viable rather than merely demoable. Matched as
raw substrings, two narrations differing only in their reference number are
different strings — every transaction needs its own rule and the rule table
never converges. Matched on the counterparty, one rule covers a payee forever.

From that follows the loop that makes the product worth paying for: a person
places one of nine identical BHIM cashback credits and places all nine, and the
rule is there for next month's statement. The queue shrinks each month instead
of staying the same size. A new rule never overturns a decision a person already
made — reclassification touches the queue only.

Three details that are less obvious than they look:

**Normalisation discards spaces, it does not collapse them.** The narration
wraps at the PDF column edge, which lands mid-token as readily as on a space
(`GODAVARI_RESTAU` / `RANT_`). Rejoining it is a coin flip, and guessing wrong
gives one payee two match keys. Discarding spaces makes the question moot, and
incidentally absorbs the bank's own inconsistency between `Arjun Gopal
Nair` and `ArjunPratapNair`.

**Self-transfers are matched approximately.** A transfer between two accounts
the client owns is a contra entry, not income or expenditure, and booking it as
either inflates both sides of the books. But a bank does not spell its own
customer's name consistently — one real statement writes the holder three ways
across its header, a NEFT line and an RTGS line. The threshold sits where a
spelling variant of one name matches and a relative sharing the surname does
not, because that is the difference between a contra and drawings.

**Seeds are deliberately thin.** Only what the bank itself did — interest it
paid, charges it levied — plus transfers between the client's own accounts.
Those mean the same thing in every set of books. A payee's meaning does not: the
sample statement maps two payments to the *same broker* to two different ledgers,
because one was a trade and one was an investment. Seeding a large opinionated
chart of accounts would be a pile of wrong assumptions to hunt down later.

---

## Rule 6 — money is a whole number of paise

Not a float, and not a `Decimal` either. `Decimal` is exact and would work, but
integers are the right unit for two reasons that only show up later:

- **Comparison across systems.** GST reconciliation subtracts our figures from
  GSTR-2B's within a one-rupee tolerance. Subtracting values quantised by two
  different systems is where "off by one paisa forever" is born. Integers have
  exactly one representation of every amount.
- **Nothing to configure.** `Decimal` arithmetic depends on a process-global,
  mutable context. A library that changes it changes the result of arithmetic
  already written and tested.

Fields carry the unit in the name — `balance_paise`, never `balance`. It is
uglier and that is the point: a mixed-unit bug is invisible at the call site and
obvious at the field. Rupees exist in two places only, the screen and the GST
tolerance, and both go through `core/money.py` to get there.

`format_inr` uses lakh and crore grouping: `₹6,03,490.57`, not `₹603,490.57`.
The wrong one is instantly visible to an Indian accountant.

---

## Rule 7 — identifiers are encrypted, and still findable

Bank account numbers and vendor GSTINs are AES-256-GCM under the firm's data
key. That protects them and destroys what the column was for: the ciphertext is
randomised, so the same account encrypts differently every time and no index,
join or uniqueness constraint can touch it — while a statement arriving and
needing to find its account is exactly that lookup.

So each encrypted identifier gets a **blind index** beside it: a keyed hash used
only for equality. Three properties are load-bearing, all in
`core.crypto.blind_index`:

- **Keyed, not a bare hash.** Account numbers and GSTINs are drawn from a small
  enough space to enumerate; a plain SHA-256 of a GSTIN is a lookup table away
  from plaintext.
- **Scoped per firm.** Equal fingerprints across the tenant boundary would leak
  that two firms bank with the same party — a correlation RLS otherwise
  prevents.
- **Separated by purpose**, so an account-number index and a GSTIN index of the
  same digits cannot collide.

`account_last4` is stored separately, so `Axis ••••7214` on a list screen costs no
decryption at all.

---

## Rule 8 — the ledger is append-only, in the database

Approval is the moment staging becomes permanent, and permanence is enforced by
PostgreSQL rather than by convention:

- **No UPDATE or DELETE grant** on `ledger_journal_entry` or
  `ledger_journal_line`. The application role holds SELECT and INSERT.
- **Triggers that raise** on either operation. Redundant on purpose: grants get
  widened by a careless later migration, triggers get lost in a restore from a
  schema-only dump, and both failing in one deployment is unlikely enough to be
  worth the duplication. The trigger's message also names the rule, which a bare
  permission error does not.
- **A deferred constraint trigger** sums each entry's lines at commit. Deferred
  because an entry is written a line at a time and is legitimately unbalanced in
  between; commit is the only point where "balanced" is a meaningful question.

That constraint improved the design it was meant to serve. The data model
sketched `supersedes_id` *and* `superseded_by_id`; writing the second would
require an UPDATE on the entry being corrected. So only the correcting entry
carries the link and the reverse direction is a query — which makes the original
not merely *treated* as untouched but untouchable. A correction posts a reversal
of the original's lines plus the corrected ones, so the trial balance is right at
every point in the chain rather than only at the end.

**Voucher numbers** come from a counter row under `SELECT FOR UPDATE`, per
client per financial year per voucher type. `MAX(entry_no) + 1` lets two
concurrent approvals read the same maximum and allocate the same number, and a
duplicated voucher number is what an audit opens with.

**Who may post, and who signs.** Posting is the preparer's act: every role above
read-only holds `journal.approve` and `journal.correct` (see `core/rbac.py`), so
staff post and correct their own work on the clients they are assigned to. What
is a senior's is the *sign-off* -- `books.sign_off`, and with it returning,
reopening, adjusting signed-off entries and deciding ledger proposals -- and that
is limited to the client's lead or a firm administrator (`core/access.py`).
Posted entries are not permanent until that sign-off, and each change before it
is kept in the change log. All of it is checked server-side; hiding a button is
not enforcement.

---

## Rule 9 — the export carries only what was approved

A voucher is derived from a journal entry at export time, never stored. The
entry is already persisted and already audited; a stored voucher would be a
third copy to keep in step, and the first time a reviewer corrects a ledger it
becomes a lie that still exports cleanly.

Reading from `JournalEntry` rather than from classifications also closes a
bypass by construction: before the ledger existed, a statement could be exported
into a client's books without anyone approving a line of it.

The one genuinely treacherous detail is Tally's sign convention: **a negative
`<AMOUNT>` is a debit and a positive one is a credit**, which is inverted from
how anyone writes it down. Get it backwards and the import succeeds, the totals
tie, and every entry in the client's books faces the wrong way. There is no
error message anywhere in that sequence, so the tests in
`ledger/tests/test_tally_export.py` are the error message.

Two more Tally behaviours worth knowing before touching that exporter:

- **An unknown ledger name is created, not rejected.** A trailing space or a
  changed capitalisation silently starts a second ledger and splits the year
  across the two. Masters are therefore exported alongside the vouchers, with
  their groups, rather than letting Tally invent them — and masters come first
  in the document, because Tally reads it in order.
- **`REMOTEID` is what makes re-import safe.** "Export again after fixing three
  classifications" is the normal case, not the exception. The id is derived from
  the transaction's dedupe hash, so it is stable across exports.

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

## Rule 10 — the API states the conventions it cannot enforce

Everything above this line is enforced by the database or by a type that refuses
to exist. An HTTP boundary can enforce far less: a client is free to parse a
number badly, ignore a status code, or format a rupee figure itself. So the API
is built to make the right thing the easy thing, and to say plainly where it is
relying on the client.

**Money crosses the wire twice.** Every amount is an integer `*_paise` and a
formatted `*_display` string. That is not redundancy -- it is the two things a
client needs, offered so it never has to derive one from the other. JSON
integers survive JavaScript intact; JSON numbers with a decimal point do not,
and a browser parsing `530.00` into a float is the rounding error the entire
backend exists to avoid, reintroduced at the last possible moment. Indian digit
grouping is likewise not something a frontend gets right by accident.

**Slow work answers 202 with a job.** The architecture asks for this and it is a
contract with every client that will ever be written, so it is in place now even
though the work still runs inline inside the request. Moving execution onto a
Celery worker is a change inside `core.jobs.run_job`; nothing a caller sees
moves. Retrofitting the shape later would mean changing every call site in a
frontend at once.

**Errors keep the domain's own words.** "Balance chain broke at row 30
(26-07-2025, 'NEFT/MB/AXOMB20702009852/...'): expected a balance of ..." tells a
person exactly what to look at. Replacing that with `400 Bad Request` throws
away the whole value of having written it. A stable `code` sits beside the prose
for clients that need to branch, and the status codes mean something: 422 for a
document that could not be read, 409 for a conflict with current state, 403 for
a role boundary -- never quietly downgraded to a 404.

**Permission checks are doubled on purpose.** A DRF permission class refuses the
request, and `ledger.approval.approve` refuses it again. Not belt-and-braces for
its own sake: the second check is the one that holds for the management
commands, and for whatever calls the domain next.

**The MFA gate answers in JSON under `/api/`.** A 302 to an HTML enrolment page
is unreadable to a `fetch()`, and an HTTP client following redirects by default
would report it as a success.

One thing the schema generator taught us, worth recording because it is the kind
of thing that only surfaces at runtime: naming a pagination class that lives
beside the view classes in `DEFAULT_PAGINATION_CLASS` is a circular import, and
DRF reports it as "module does not define DefaultPagination" -- the symptom, not
the cause. It lives in `api/pagination.py`, which imports nothing from the rest
of the project.

---

## Rule 11 — the edges refuse before the middle has to

Everything RLS and the append-only ledger guarantee is about data already in
the system. The edges -- the login form, the upload endpoint, the headers on
every response -- guard against what never should get that far.

**Lockouts are counted per address and per account**, in the cache, and checked
before a password is hashed (`core/throttle.py`). Two keys because each closes
the gap the other leaves: rotating addresses is caught on the account, spraying
accounts is caught on the address. A correct password after nine wrong ones is
still refused for the window; a lockout that a right guess resets is not a
lockout. A locked-out caller cannot tell a real account from an invented one.
Multi-process deployments must share the cache (`CACHE_URL`), and
`check --deploy` says so.

**An upload is a PDF of a plausible size, or it is refused at the serializer.**
The filename and declared content type are the caller's; the signature bytes
and the size are not.

**`X-Forwarded-For` is trusted exactly `TRUSTED_PROXY_COUNT` hops deep**, read
from the right. With zero proxies it is ignored. The audit log records where a
request came from, not where it said it came from. `X-Request-ID` is accepted
only as a short token.

**Every response carries a strict Content-Security-Policy** (`self` only, no
inline script or style, no framing, forms post here). The application shell is
built to live under it -- Vite emits external assets, and the CSS has no inline
exceptions. Two page families cannot: the OpenAPI viewer (a CDN script with
inline bootstrap) and the Django admin (inline scripts of its own). Each gets a
documented looser policy by path prefix, still without framing.

**Every log record is masked** (`core/logging.py`) with the same function the
classifier uses before a model sees a narration (`core/masking.py`). One
implementation, so the two cannot disagree about what counts as identifying.
The exception messages in this codebase quote the data that broke -- right for
the person reading the failed job, wrong for a log aggregator with ninety days
of retention -- and this is what squares the two.

**An unexpected exception never reaches an API caller.** The domain's own
errors are passed through verbatim because they were written to be read. A
stray driver error is not: it quotes whatever it was holding. `job.error` gets
a sentence and the job id; the traceback is in the log under that id.

## The model tier, and what leaves the building

The classifier's third tier (`classify/llm.py`) runs after the rules and before
a person, and three rules bound it.

It only suggests. A model-sourced row lands in the ADVISED band with a one-line
rationale, capped at 0.89 -- strictly below the band eligible for bulk approval
-- so a person looks at every one. A suggestion the model itself rates below
the review threshold is not recorded as a suggestion; the row stays unresolved
with the reasoning attached. The requirements document's line about a confident
wrong answer being worse than an honest "I don't know" is implemented as those
two numbers.

It only sees pseudonymised rows (`classify/pseudonymise.py`): the narration
masked by `core.masking`; known vendors as their alias token; people as stable
pseudonyms; the account holder never; amounts as bands; and the client's ledger
names. Business names are sent, because "GODAVARI RESTAURANT" is the signal and
a company is not a person -- and `LLM_SHARE_BUSINESS_NAMES=0` turns even that
off for a firm that wants only aliases. The model answers with a ledger *name*,
validated against the list it was given; an invented one is discarded.

It cannot fail the pipeline. A provider outage is a warning in the log and a
line on the job; the upload has already succeeded and the rows are in the queue
for a person either way.

Approving a model suggestion teaches a rule, so the same payee is a rule hit in
the high band next month rather than another model call and another review.

Groq is the first provider (`integrations/llm/groq.py`): plain HTTP,
temperature 0, JSON mode, bounded retries on 429/5xx only, no SDK. Its default
terms do not commit to zero retention, which is acceptable exactly because
nothing identifying is sent. Moving to in-country inference is `LLM_BACKEND`
and one new file.

## The web application

`web/` is a React SPA built by Vite into static files and deployed on its own
(a static host with a rewrite of `/api/` and `/auth/` to this server, so the
browser stays on one origin). The backend serves none of it: `FRONTEND_URL`
tells the backend where it lives, for the redirect from `/`, invitation links,
and the CSRF trusted origin a proxy needs. It is written to move into Tauri
without a rewrite; see `web/README.md`.

The page drives the second factor itself through the JSON endpoints -- the
provisioning URI is drawn as a QR code client-side. Everything the page *shows*
comes from `/api/`, which is exempt from nothing. Authentication is the session cookie; there is no token in
JavaScript to steal, and every mutating call carries the CSRF header.

The permission list from `/api/v1/me/` decides what the screens *offer*. It
decides nothing about what the server *allows* -- every permission is checked
again on every request, and a hidden button is not a permission system.

---

## Month end is the check that catches what the others miss

Everything else verifies that a step did what it was told. Comparing the
computed bank-ledger balance against the statement's own closing figure verifies
that the *result* is right — and catches a row posted twice, a correction
reversed the wrong way, or an entry approved against the wrong account, in one
subtraction. It is also the check the firm already does by hand, so it is the
one they will look at first.

A mismatch blocks the period from being marked reviewed, and the report
distinguishes "does not reconcile" from "not finished yet" — the second is the
common case, and sending someone hunting for the first wastes an afternoon.

---

## Three migration traps, all found the hard way

Both bite any new firm-scoped table, and both produce an error that names the
tenancy layer while the fault is elsewhere.

**RLS cannot go in the same migration as the table.** Django opens one schema
editor per migration and flushes its `deferred_sql` — where foreign key
constraints live — when that editor closes, *after* every operation has run. So
an `rls_operations()` call appended to a `CreateModel` migration is applied
before the foreign keys are. Split them; see
`banking/migrations/0002_row_level_security.py`.

**A deferred trigger fires after the tenant context is gone.** The balance check
runs during COMMIT, by which point `firm_context()` has cleared the GUC on its
way out — so the trigger's own `SELECT` hits the table's RLS policy with no
context and raises `tenant context missing`, which reads like a tenancy bug and
is really a lifecycle one. The trigger now sets the context from the row it is
checking. That is not a hole: the only value it can set is the firm owning the
row being inserted, which the inserting transaction already had.

**A table-creating migration needs a tenant context of its own.** Adding a
foreign key makes PostgreSQL validate it by scanning the child table and joining
the parent:

```sql
SELECT fk.client_id FROM ONLY banking_bank_account fk
LEFT OUTER JOIN ONLY core_client pk ON pk.id = fk.client_id
WHERE pk.id IS NULL AND fk.client_id IS NOT NULL
```

`core_client` is already behind `FORCE ROW LEVEL SECURITY`, so that scan raises
`tenant context missing` and takes the migration with it. FORCE is what makes it
bite — the owner role running the migration is subject to the policies too,
which is the entire point of FORCE and is not negotiable. The fix is
`ddl_tenant_context_operations()` as the **first** operation of the migration:
it sets a reserved firm id that matches nothing, which is enough to answer the
scan. It has to be first because the deferred SQL flushes last, and the
transaction-scoped setting is still in force then.

The caveat is documented at the call site and is worth repeating: under that
context the scan sees zero rows, so it validates nothing. Harmless for a
migration that creates an empty table. For one that adds a foreign key to a
populated table, validate per firm afterwards rather than trusting the
constraint's VALID flag.

## Verifying the guarantees

```bash
python manage.py check --deploy --database default   # role privileges, middleware order
python manage.py rls_status                          # live ENABLE/FORCE/policy per table
pytest core/tests/test_rls_isolation.py              # cross-tenant attack suite
pytest integrations/tests/test_adapter_swap.py       # adapter boundary + envelope crypto
pytest banking/tests/test_balance_chain.py           # the arithmetic gate, attacked directly
pytest ledger/tests/test_approval.py                 # immutability, via the ORM and raw SQL
pytest ledger/tests/test_tally_export.py             # double entry and Tally's sign convention
pytest ledger/tests/test_reconciliation.py           # month end: the books against the bank
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
