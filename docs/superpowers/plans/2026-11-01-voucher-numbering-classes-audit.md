# Voucher numbering, classes and the audit trail: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Tally's voucher number, let a firm's own voucher types keep their own numbering series and number format, add voucher classes for sales and purchase, and give the accountant one audit screen covering vouchers and masters.

**Architecture:** `JournalEntry.voucher_type` stays the parent standard type (all accounting code is untouched); a new `type_name` on entries and sequences names a custom series ("" is the standard one), and the numbering unique keys include it. Formats, custom types, classes and master changes are new client-scoped tables with the same tenant isolation as `ledger_tally_voucher`. Master changes are written by the existing viewsets; one endpoint merges them with `EntryChange` rows.

**Tech Stack:** Django/DRF, `core.db.rls` (`rls_operations`, `append_only_operations`), React/TanStack Query, pytest on the local Postgres at port 5434 (never the live tunnel at 5433).

**Spec:** `docs/superpowers/specs/2026-11-01-voucher-numbering-classes-audit-design.md`

## Global Constraints

- The stored number stays an integer; format only changes how it is shown. Default format is no prefix, no padding, so nothing changes until chosen.
- `JournalEntry.voucher_type` keeps meaning the accounting parent. A custom type never changes how an entry posts.
- Two series with the same parent in one year may both hold number 1; the same series never repeats a number.
- Every new table is firm-scoped with row-level security and, where it names a client's ledger or entry, a same-client composite foreign key (pattern: `ledger/migrations/0035_tally_vouchers_security.py`).
- `MasterChange` is append-only at the database (`append_only_operations`).
- Voucher classes cover sales and purchase only.
- DB tests: source `E:\autoca-local\env.sh`, then export `DATABASE_URL` and `DATABASE_OWNER_URL` as `postgresql://autoca_ci:ci@localhost:5434/autoca`. Never push or deploy without the user naming it.

## Review Focus

- Sales and a custom "GST SALE" series both number 1 in the same client and year: no collision, no shared counter.
- Sign-off renumbering keeps each series gapless on its own and never moves an entry between series.
- Changing a type's format afterwards re-renders its numbers everywhere and changes no stored integer.
- An entry with no Tally number shows no label and nothing breaks; a search for a Tally number finds only that client's entries.
- A person without edit permission cannot change a ledger, party or rule, and no master-change row can be edited or deleted.

---

### Task 1: Show Tally's number

**Files:**
- Modify: `api/serializers/ledger.py` (`JournalEntrySerializer`), `api/views/ledger.py` (prefetch `tally_voucher`; Day Book search), `web/src/features/daybook/DayBookScreen.tsx`, `web/src/features/review/PostedEntries.tsx`
- Test: `api/tests/test_tally_numbers.py`, `web/src/features/daybook/DayBookScreen.tallyNumber.test.tsx`

**Interfaces:**
- Produces: `JournalEntrySerializer` fields `tally_number: str` and `tally_type: str` (empty when the entry did not come from Tally); the Day Book entries list accepts `?q=` also matching `tally_voucher__tally_number`.

- Party statements and ledger rows that list entries use the same two fields when they come from `JournalEntrySerializer`; where a list uses another serializer, add the same two fields there and a test for each.

- [ ] **Step 1: Write failing tests**: `test_an_imported_entry_carries_its_tally_number_and_type` (import one Purchase numbered "138", GET the entries, assert `tally_number == "138"` and `tally_type == "Purchase"`); `test_an_entry_not_from_tally_has_empty_tally_fields`; `test_the_day_book_search_finds_an_entry_by_its_tally_number` (and a second client's same number is not returned); web test: a row with `tally_number: "138"` renders "Tally 138", a row without renders no such label.
- [ ] **Step 2: Run** `pytest api/tests/test_tally_numbers.py -q` and `npx vitest run src/features/daybook` — expect FAIL.
- [ ] **Step 3: Implement** the two read-only serializer fields from the reverse `tally_voucher` relation (select_related it in the queryset), the search clause, and the label beside the voucher number in the Day Book row and posted-entries row.
- [ ] **Step 4: Run** the same commands plus `npx tsc --noEmit` — PASS. **Step 5: Commit** "Show Tally's voucher number beside ours".

### Task 2: Models and migrations

**Files:**
- Modify: `ledger/models.py`
- Create: `ledger/migrations/0039_voucher_series_classes_audit.py`, `ledger/migrations/0040_voucher_series_classes_audit_security.py`
- Test: `ledger/tests/test_voucher_series_models.py`

**Interfaces:**
- Produces: `CustomVoucherType(client, name: str<=64, parent: VoucherType)`, unique `(firm, client, name)`; `NumberingFormat(client, voucher_type, type_name: str, prefix: str<=16, padding: int 0..8)`, unique `(firm, client, voucher_type, type_name)`; `VoucherClass(client, name<=64, voucher_type in {Sales, Purchase}, type_name, head_ledger FK, cgst_ledger FK null, sgst_ledger FK null, igst_ledger FK null, gst_rate: Decimal(5,2) null)`, unique `(firm, client, name)`; `MasterChange(client, kind in {LEDGER, GROUP, PARTY, RULE}, object_id UUID, action in {CREATED, EDITED, REMOVED}, label: str<=255, before JSON, after JSON, actor FK null)`; new field `type_name: CharField(64, blank, default="")` on `JournalEntry` and `VoucherSequence`; `uniq_voucher_sequence` and `uniq_voucher_number_per_book` recreated to include `type_name`.

- [ ] **Step 1: Write failing tests** (DB): `test_two_series_with_the_same_parent_can_both_hold_number_one` (two entries, `voucher_type=Sales`, `type_name` "" and "GST SALE", both `entry_no=1`, same year: saves; a third `("GST SALE", 1)` raises `IntegrityError`); `test_a_class_cannot_name_another_clients_ledger` (composite-FK refusal); `test_a_master_change_row_cannot_be_updated_or_deleted`; `test_a_numbering_format_is_unique_per_series`.
- [ ] **Step 2: Run** `pytest ledger/tests/test_voucher_series_models.py -q` — FAIL.
- [ ] **Step 3: Implement** the models, generate `0039` with `makemigrations` (the new constraints in it), hand-write `0040` using `rls_operations(...)` for the four tables, `append_only_operations("ledger_master_change")`, and same-client composite FKs for `VoucherClass`'s ledger columns.
- [ ] **Step 4: Run** the tests, `manage.py makemigrations --check --dry-run` (none) and the existing `ledger/tests/test_tally_voucher_import.py` — PASS. **Step 5: Commit** "Voucher series, formats, classes and master changes: tables".

### Task 3: Numbering by series and format

**Files:**
- Modify: `ledger/approval.py` (`allocate_voucher_number`), `ledger/editing.py` (renumbering at sign-off), `api/serializers/ledger.py`
- Create: `ledger/numbering.py`
- Test: `ledger/tests/test_numbering_series.py`

**Interfaces:**
- Consumes: Task 2 models.
- Produces: `allocate_voucher_number(client, year: int, voucher_type: str, type_name: str = "") -> int` (existing callers unchanged); `format_voucher_number(client, voucher_type: str, type_name: str, number: int, financial_year: int) -> str` in `ledger/numbering.py` (prefix may contain `{fy}` replaced by `25-26`; number zero-padded to `padding`); serializer field `voucher_number: str` on entries.

- [ ] **Step 1: Write failing tests**: `test_each_series_counts_on_its_own` (allocate for `("Sales","")` twice and `("Sales","GST SALE")` once → 1, 2, 1); `test_the_format_prefixes_and_pads` (prefix `S/{fy}/`, padding 4, number 7, FY 2025 → `S/25-26/0007`); `test_no_format_shows_the_plain_number`; `test_changing_the_format_changes_the_shown_number_not_the_stored_one`; `test_sign_off_renumbering_keeps_each_series_gapless_and_apart`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the allocator keyed by `type_name` (same row lock), `format_voucher_number`, the renumbering loop grouped by `(voucher_type, type_name)`, and the serializer field.
- [ ] **Step 4: Run** the new tests and `pytest ledger -k "approval or editing or sign"` — PASS. **Step 5: Commit** "Number each voucher series on its own, with a format".

### Task 4: A firm's own voucher types

**Files:**
- Modify: `ledger/tally_plan.py` (`Planned.type_name`, `own:` answers), `ledger/tally_voucher_import.py` (`_write` allocates in the custom series, creates the `CustomVoucherType`), `api/views/ledger.py` + `api/urls.py` (CRUD), `api/serializers/ledger.py`, `web/src/features/tally/TallyImportScreen.tsx`
- Test: `ledger/tests/test_tally_custom_types.py`, `api/tests/test_voucher_types_api.py`

**Interfaces:**
- Consumes: `allocate_voucher_number(..., type_name)`; `MAPPABLE_TYPES`.
- Produces: a voucher-type answer `"own:<standard type>"` (for example `own:sales`) accepted wherever `voucher_types` is; `Planned.type_name: str = ""`; `GET/POST clients/{id}/voucher-types/` and `PATCH/DELETE clients/{id}/voucher-types/{id}/` (name, parent; delete refused while an entry uses it); screen choice "Keep as its own voucher type (counts as Sales)" beside the existing choices.

- [ ] **Step 1: Write failing tests**: `test_an_own_type_posts_as_its_parent_and_numbers_in_its_own_series` (import GST SALE vouchers with `own:sales`: entries have `voucher_type == "Sales"`, `type_name == "GST SALE"`, `entry_no` 1..n, and a hand-made Sales voucher is also 1); `test_the_own_type_is_created_once`; `test_a_voucher_type_in_use_cannot_be_deleted`; API: create/rename/delete; web: choosing the "own" option sends `own:sales`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** parsing of `own:` in `normalise_type_map`/`plan_voucher`, the write path, the viewset (permission `ledger.import`) and the screen option.
- [ ] **Step 4: Run** the tests plus `pytest ledger/tests/test_tally_plan.py ledger/tests/test_tally_voucher_import.py`, `npx tsc --noEmit`, `npx vitest run src/features/tally` — PASS. **Step 5: Commit** "A firm's own voucher types keep their own series".

### Task 5: Number format settings

**Files:**
- Modify: `api/views/ledger.py`, `api/serializers/ledger.py`, `api/urls.py`; Create: `web/src/features/books/NumberingSettings.tsx`; Modify: `web/src/features/books/BooksScreen.tsx`
- Test: `api/tests/test_numbering_api.py`, `web/src/features/books/NumberingSettings.test.tsx`

**Interfaces:**
- Consumes: `NumberingFormat`, `format_voucher_number`.
- Produces: `GET/PUT clients/{id}/numbering/` — a list of `{voucher_type, type_name, prefix, padding, example}` (every standard type plus each custom type; `example` is the next number as it will read); PUT validates `prefix` (at most 16 characters, no spaces or slashes other than `/`, `-`, `{fy}`) and `padding` 0 to 8; permission `books.settings` (use the permission the client profile edit uses).

- [ ] **Step 1: Write failing tests**: GET lists all standard types with empty prefix; PUT sets `S/{fy}/` and padding 4 and the `example` becomes `S/25-26/0001`; PUT with padding 12 is 400; a viewer without edit permission gets 403; web test renders each series with its example and saves a change.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** endpoint, serializer and the settings card on the Books screen.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** "Number format per voucher type".

### Task 6: Voucher classes (sales and purchase)

**Files:**
- Modify: `api/views/bills.py` (or the module serving `bills/`), `api/serializers/*`, `api/urls.py`, `web/src/features/bills/VoucherForm.tsx`
- Create: `web/src/features/books/VoucherClassesSettings.tsx`
- Test: `api/tests/test_voucher_classes_api.py`, `web/src/features/bills/VoucherForm.classes.test.tsx`

**Interfaces:**
- Consumes: `VoucherClass`.
- Produces: `GET/POST clients/{id}/voucher-classes/`, `PATCH/DELETE .../{id}/` (fields: `name`, `voucher_type` in Sales/Purchase, `type_name`, `head_ledger`, `cgst_ledger`, `sgst_ledger`, `igst_ledger`, `gst_rate`); in `VoucherForm`, a "Class" select (shown when the type has classes) that fills the head ledger, the tax ledgers and the rate, which the person can still change.

- [ ] **Step 1: Write failing tests**: API CRUD, 400 when a ledger belongs to another client, 400 for a voucher type other than Sales/Purchase; web: choosing a class fills the ledgers and rate in the form, and editing a filled field keeps the edit.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the viewset (permission `suggestion.edit`), the settings card, and the form's class select (prefill only, nothing posts differently).
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** "Voucher classes for sales and purchase".

### Task 7: Audit trail for vouchers and masters

**Files:**
- Create: `ledger/audit.py`, `api/views/audit.py`, `web/src/features/books/AuditTrailScreen.tsx`, `web/src/routes/_app/clients/$clientId/audit.tsx`
- Modify: `api/views/classify.py` (ledger, party and rule viewsets call the recorder), `api/urls.py`, `web/src/features/books/BooksScreen.tsx` (tab)
- Test: `ledger/tests/test_master_audit.py`, `api/tests/test_audit_trail_api.py`, `web/src/features/books/AuditTrailScreen.test.tsx`

**Interfaces:**
- Consumes: `MasterChange`, `EntryChange`.
- Produces: `record_master_change(client, kind: str, obj_id, action: str, *, label: str, before: dict, after: dict | None, actor) -> MasterChange` in `ledger/audit.py` (called after a successful create, update or delete by `LedgerAccountViewSet`, `PartyViewSet`, `RuleViewSet`); `GET clients/{id}/audit-trail/?from=&to=&actor=&kind=&q=&page=` returning rows `{at, actor_name, kind, action, label, before, after}` merged newest first from `EntryChange` (kind `ENTRY`) and `MasterChange`, paged.

- [ ] **Step 1: Write failing tests**: renaming a ledger writes one `MASTER` row with the old and new name and the actor; deleting a rule writes a REMOVED row; a viewer cannot change a master (403) and no row is written; the endpoint merges an entry edit and a ledger rename in time order; filters by actor and kind; one client cannot read another's rows; web: the screen lists rows, filters by kind and shows before and after for a row.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the recorder, wire the three viewsets (`perform_update`, `perform_create`, `perform_destroy`), the merged read endpoint (permission `report.view`) and the screen with its tab.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** "Audit trail across vouchers and masters".

### Task 8: Docs, schema and whole-branch verification

**Files:** Modify `docs/ARCHITECTURE.md`, `web/openapi.yaml`, `web/src/api/schema.d.ts`.

- [ ] **Step 1:** Add the numbering, custom types, classes and audit design notes to the architecture doc.
- [ ] **Step 2:** `npm run gen:api` in `web/` with the local environment; confirm `manage.py spectacular` shows no drift.
- [ ] **Step 3: Run** `ruff check .`, `manage.py makemigrations --check --dry-run`, `npx tsc --noEmit`, `npx vitest run`, and `pytest ledger api banking core classify -p no:cacheprovider` on port 5434 — all PASS (name any red test).
- [ ] **Step 4: Commit** "Docs and schema for numbering, classes and the audit trail". Do not push.
