# Tally import (replaces Tally export)

Status: design only, nothing built. Branch `preview/r2-redesign`. The user: "we need tally import not tally export ... we wanna replace tally basically". Decided: files uploaded in the web app (no desktop helper, no live link); the existing export is removed. Not yet decided: scope. This note assumes **phase A = chart + opening balances** and outlines **phase B = prior vouchers as read-only history**.

Things marked (unverified) come from memory of Tally, not from a file. We have no real sample; see section 8.

## 1. Formats

What the firm exports per client company, for the financial year being taken over:

1. **Ledger masters, XML.** Tally Prime: Export (Alt+E) > Masters > ledgers, format XML (Data Interchange). ERP 9: Gateway of Tally > Export > Masters. (menu path unverified). This is the primary input: one `<LEDGER NAME>` per ledger, with `PARENT` (its group), `OPENINGBALANCE`, alias (`LANGUAGENAME.LIST/NAME.LIST/NAME`), and for parties GSTIN (`LEDGSTREGDETAILS.LIST/GSTIN`), `ISBILLWISEON`. The groups arrive as `<GROUP NAME><PARENT>` messages (user-made groups included; export Groups with it). Same TALLYMESSAGE/ENVELOPE shape `ledger/tally.py` writes today, though Tally's real export wraps it in `BODY/DATA/TALLYMESSAGE` rather than `IMPORTDATA/REQUESTDATA` (unverified), so the parser must find `LEDGER` and `GROUP` elements by tag, not by a fixed path.
2. **Same masters as Excel/CSV** (Display > List of Accounts > Alt+E > Excel, or CSV). Flat: group, ledger, opening Dr/Cr. Second-class: no hierarchy beyond the group column, no GSTIN, no alias. Accept it as a fallback, parsed with `openpyxl`, which we already ship (`requirements/base.txt`).
3. **Trial Balance for the year, as Excel or XML**: used only as a cross-check. After parsing we total each group's opening from the masters and compare with the TB's opening column. A mismatch is shown in the preview, not blocking.

Sign convention (Tally): in XML a **negative amount is a debit**, positive a credit; `OPENINGBALANCE` follows it (unverified for masters; `tally.py` confirms it for vouchers). In Excel it is usually "12,345.00 Dr". Parse to signed integer paise with `core/money.py`, never float. Reject more than two decimals.

Encoding: Tally often writes UTF-16 with a BOM, and sometimes control characters that break XML 1.0. Detect the BOM, decode, strip illegal characters, then parse (unverified, test with a real file).

**Trap: ledger `OPENINGBALANCE` is the balance at the company's "books beginning from" date, not necessarily at our FY start.** For a company that began earlier, the FY-start figure is the previous year's closing, which only the Trial Balance (as at FY start) or a per-year export shows. So the upload asks for the FY, the preview shows the file's own books-from date if present (`COMPANY/BOOKSFROM`, unverified), and refuses an opening file when it is clearly not at the chosen FY start. Needs a sample.

**Group mapping.** Our `LedgerGroup` has 13 values; Tally has about 28 predefined groups plus user groups and nesting. A ledger's group is resolved by walking `PARENT` up to a predefined primary group. A fixed table maps Tally primaries to ours (Sundry Debtors, Sundry Creditors, Bank Accounts, Cash-in-Hand, Duties & Taxes, Direct/Indirect Income/Expense, Capital Account, Loans (Liability), Investments, Suspense A/c map directly). **Gaps that matter:** Fixed Assets, Stock-in-Hand, Loans & Advances (Asset), Deposits (Asset), Current Assets, Provisions, Reserves & Surplus, Sales Accounts, Purchase Accounts, Bank OD. `ledger/reports.py` treats any group not in `ASSET_GROUPS` as a liability, so an unmapped asset would land on the wrong side of the Balance Sheet. Recommendation: add the missing values to `LedgerGroup` (a choices-only change, no SQL) and update `ASSET_GROUPS` and `PROFIT_AND_LOSS_GROUPS` in the same change, and store the original Tally group path on the ledger for display. A user primary group has no mapping: the preview asks which of our groups it belongs to (nature Assets/Liabilities/Income/Expense is read from the group's own flags if present).

## 2. Import flow

Permission: new `ledger.import`, role-held by firm admin and senior CA; plus `can_sign_off(membership, client)` (lead or admin) as the object rule, because importing replaces the client's chart. Staff cannot. Server-side only.

1. `POST /clients/{id}/tally-imports/` (multipart, `file`, `financial_year`). Limits like the statement upload: `.xml`, `.xlsx`, `.csv`; 25 MB (`MAX_STATEMENT_UPLOAD_BYTES` pattern, a separate lower setting, say 10 MB); content sniffed, not trusted from the extension. XML parsed with **`defusedxml`** (not installed today; add to `requirements/base.txt`; this is a dependency change to approve): DTD, external entities, entity expansion all refused. Count of ledgers capped (say 20,000), name length 255. Parsing runs inline for masters (fast), not in a job.
2. The parse produces a **staging record** (an `ImportRun` with status `PREVIEW` plus rows as JSON, section 6), never touching `LedgerAccount`. Response is the preview.
3. Preview classifies each row:
   - **create**: no ledger of that normalised name (casefold, collapse inner spaces, strip, NFKC).
   - **match**: same normalised name and same group: nothing to create; opening balance still applies.
   - **conflict, group differs**: person picks keep-ours or take-Tally's (default keep ours; moving a ledger with posted lines is refused: lines already carry a meaning).
   - **conflict, names differ only by case or spaces from an existing ledger, or two rows in the file collide**: shown paired; person chooses which spelling survives (renaming through the existing ledger rename, which moves entries with it).
   - **reserved**: names we reserve (`Suspense A/c`, `Cash-in-Hand`, `Bank Interest Received`, `Bank Charges`, `Profit & Loss A/c`, `Difference in opening balances`) are never silently created or renamed. Matching seeds adopt as `match`; a different group is a conflict.
   - **skipped**, with a reason: Tally's built-in `Profit & Loss A/c` and `Primary` groups, duties/stock items we cannot hold, inactive-looking rows with no balance, rows with an unreadable amount.
4. The person confirms with the run id and their conflict choices: `POST .../tally-imports/{run}/confirm/`. One transaction creates ledgers and openings (section 3). Idempotent: the file hash is stored, and confirming again, or uploading the same file, creates nothing (create is by normalised name, openings are `update_or_create` by (ledger, FY)). A second, different file for the same FY is allowed until books are signed off through that FY and replaces the openings it covers.
5. Every string is untrusted: names, aliases, group names are length-limited, stripped of control characters, and kept as data; later Excel exports of ledger lists must neutralise a leading `= + - @` (the SEC-001 lesson; reuse the helper in `gst/report.py`). No name is logged; the audit event records counts and the run id, never the contents.

Errors (plain, 4xx, never 500), added to `api/exceptions.py`: `tally_file_unreadable` (422), `tally_file_too_large` (413), `tally_year_mismatch` (422), `tally_run_stale` (409, preview older than a change to the chart), `entry_locked` (409, reused, section 3).

## 3. Opening balances

Recommended: **do not post them as a journal entry.** `ledger/reports.py::_balances` already models openings outside the journal: the confirmed bank opening is added to the bank ledger, with the counterpart shown as `Difference in opening balances`. A synthetic opening entry would get an `entry_no` in the FY's `VoucherSequence` (and shift every number), count as in-year movement if dated on the FY start, belong to the previous FY if dated the day before, and then appear in the Day Book. It would also be permanent, so a wrong import could only be reversed. Instead:

- New table `LedgerOpening` (client, ledger, financial_year, `signed_paise` debit positive, import run). Mutable until the FY is signed off, because it is a starting position, not a transaction; every change is audited. Reports add it to `opening` exactly where they add the bank opening today, and `Difference in opening balances` becomes the sum of all openings (which is zero when Tally's opening balanced), so the Trial Balance still balances. A Tally opening that does not balance remains visible under that existing name.
- If we later prefer a real journal entry (the user's lean), the same staging works and only the write step changes; the cost is the three problems above.

Refuse when the client's books are signed off through a date on or after the FY start: `entry_locked`, the same wording as `confirm_opening_balance`. A client that already has posted entries in the FY is not refused: a chart import is useful then, and openings do not change their entries; the preview says "N entries already posted this year; the Trial Balance will change by the openings".

**Bank agreement.** `BankAccount.opening_balance_paise` (+ `opening_as_of`) is a second source for the same number. The importer maps a bank-group ledger to a bank account by the account's `ledger_name`. Rules: if the account has no confirmed opening, the import proposes it and, on confirm, calls `confirm_opening_balance` (so its lock rule applies) and stores no `LedgerOpening` for that ledger; if both exist and differ, the preview flags a conflict with both figures and the person picks one; the other is not written. Reports must then never add both, so `_balances` skips a ledger that has a bank account opening.

## 4. Phase B outline (prior vouchers)

Same staging pattern. Input is the Day Book / vouchers XML, `VOUCHER` elements with `ALLLEDGERENTRIES.LIST`. Each voucher is staged with its lines resolved to ledgers (an unknown ledger blocks the voucher; party matched by ledger name, then GSTIN). Voucher types: Payment/Receipt/Contra/Journal map directly; Sales, Purchase, Credit/Debit Note, stock vouchers are **not** in `VoucherType` and are out of scope for the first cut. Numbering: keep Tally's own number as a reference; our `entry_no` stays gap-free per type/FY from `VoucherSequence`, so the sequence is allocated at import in date order. Marker: new `EntryMarker` value `IMPORTED` ("Imported from Tally"), never clearable. Permanence: imported entries enter the append-only journal, so the preview is the review, a reconciling total per month (Tally's vs ours) is required, and the run ends with an immediate sign-off through the last imported date (blocking later edits, with senior reopen as the only way back). Not imported: bill allocations, stock, GST ledger detail, cost centres, deleted or optional vouchers, anything dated after the FY end. Phase A leaves room: `ImportRun` has a `kind`, and `LedgerAccount` keeps the Tally name and alias.

## 5. Removing the Tally export

Delete (one change set, in this order so the build never breaks):

1. **Frontend first** (`web/`, frontend-dev): `StatementsScreen.tsx` (`exportTally`, the "Tally XML" button, `TallyExport` import, `saveText` if unused), `BooksScreen.tsx` lines 146-153 (the "Export to Tally" block), `SoonScreen.tsx:26` copy, `web/src/api/types.ts:35`. Then regenerate `openapi.yaml`/`schema.d.ts` after the backend step.
2. **Backend**: `ledger/tally.py`; `TallyExportView` and its import in `api/views/ledger.py`; the `root.register("statements", TallyExportView, ...)` line and import in `api/urls.py`; `TallyExportSerializer` in `api/serializers/ledger.py`; `api/tests/test_api.py::test_the_tally_export_carries_only_approved_entries`; `ledger/tests/test_tally_export.py`; `documents/models.py` kind `TALLY_EXPORT` (leave it: stored rows, and removing it needs a choices migration; rename later).
3. **Docs**: `docs/ARCHITECTURE.md` "ledger/tally" diagram line 18, line 4 intro, line 61, Rule 9 (lines 463-488; keep its first idea, "derived at read time, nothing stored twice", only if it still describes reports), the test-list line 766; `docs/design/*` mentions.
4. **QA**: `web/qa/journeys/ca-r1-tallyxml.mjs`, `sca-r1-tally.mjs`, `sca-r1-tally2.mjs`, `web/qa/private/tally.mjs` and the `tally-export` calls in `sec-r1-*.mjs`, `r1-api-*`, `real-*`; orchestrator edits `web/qa/`, not the developers.

Stays (only words): Contra, Day Book, Trial Balance, "Difference in opening balances", group names, `VoucherType` and `LedgerGroup` docstrings, `ledger_name` fields, "the Trial Balance does not tally". Rewrite the copy that tells people names must match Tally (`MastersScreen`, `LedgerPicker`, `StatementsScreen`, `banking/models.py`, serializers' help_text, openapi descriptions): once Tally is replaced, "must match Tally exactly" is wrong. The splitting warning (a name differing by case splits the books) stays, reworded to "our own ledger".

CA-009 (Tally XML had no opening balance; unsigned file not marked draft): **moot** entirely. Its numbering-before-sign-off observation (CA-009 part 2) still stands as a UX note for the Day Book, not for an export.

## 6. Data model and migrations

**MIGRATION**, additive only (TEAM.md rule 5: nullable or `db_default`, ships before the code, backward-compatible with the running release):
- `ledger_import_run` (new table, no lock on existing tables): firm, client, kind (`CHART_OPENING`), financial_year, uploaded_by, created_at, file_sha256, source_format, status (`PREVIEW/CONFIRMED/DISCARDED`), counts (JSON), staged rows (JSON, name/group/opening only, no files kept; expire 7 days), confirmed_by/at. Tenant-scoped like every table: RLS on `firm_id`.
- `ledger_opening` (new table): firm, client, ledger FK PROTECT, financial_year, `signed_paise` BigInteger, run FK; unique (firm, client, ledger, financial_year).
- `classify_ledger_account`: add nullable `tally_name`/`alias` and `tally_group_path` (`null=True`), and new `LedgerGroup` choices (state-only AlterField). Small table, no rewrite.
Reversible: yes (drop tables/columns). New tables need the row-level-security policy and the test that proves it, as every tenant table has.

## 7. API and screens

- `POST /clients/{id}/tally-imports/` multipart `{file, financial_year}` -> 201 `{id, status, rows:[{name, tally_group, our_group, opening_paise, action, conflict?}], counts:{create, match, conflict, skipped}, tb_check?:{ok, differences}}`.
- `GET /clients/{id}/tally-imports/` (history), `GET .../{run}/`.
- `POST .../{run}/confirm/` `{resolutions:[{row, choice}]}` -> `{created, matched, openings, difference_paise}`; 409 if any conflict unresolved (`tally_conflicts_unresolved`).
- Screens: an "Import from Tally" step in New client onboarding (skippable), and a button under Bookkeeping > Ledgers. Steps: pick year and file, then the preview table (grouped by action, conflict rows first with a radio per row, a bank-agreement panel, the Dr/Cr total and the difference shown plainly), then the result. All amounts in `formatPaise`. CONTRACT CHANGE for frontend-dev when built.

## 8. Tests, and questions

Tests: a synthetic builder `ledger/tests/tally_xml.py` producing masters XML (with `ET`, UTF-16 variant, user groups, nested groups, aliases, `&` in names) and Excel via `openpyxl`; no real data. Parser: sign convention both ways, group walk, bad XML, XML bomb and external entity (must not fetch or expand), oversized, wrong type, formula-looking names. Flow: create/match/conflict/reserved/skip, same file twice changes nothing, permissions (staff denied, junior, other firm 404, lead/admin allowed), signed-off refusal, bank agreement both ways, openings keep the Trial Balance balanced, tenant isolation with RLS. Removal: the old route is a 404.

Questions for the user: (1) a **sample from a real Tally company, anonymised** (ledger names and amounts changed, structure kept): the Ledgers/Groups master export (XML and Excel) and the Trial Balance for one FY, from Tally Prime and, if clients use it, ERP 9; (2) is the opening balance for a company whose books began in an earlier year taken from the year's Trial Balance? (3) may we add `defusedxml`? (4) openings as a table (recommended) or a posted journal entry? (5) do we add Fixed Assets, Stock-in-Hand and the other missing groups now? (6) phase B scope: which voucher types?
