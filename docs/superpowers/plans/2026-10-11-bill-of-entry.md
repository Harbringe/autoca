# Bill of Entry (imports) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a Bill of Entry as a bill on the credit side owed to Customs, post its duties (landed cost and input IGST/cess) in one journal, settle it with ordinary bank payments (whole or in pieces), tie it to the GSTR-2B `IMPG` row, and flag the gaps as open items.

**Architecture:** A new `BillKind.IMPORT_DUTY` with a one-to-one `BillOfEntry` side record. `ledger/boe.py` holds the pure duty split first and the posting service second, reusing `billing._post` so permissions, sign-off lock, numbering and the database guards all apply unchanged. Settlement, open amount and party reports reuse the bill machinery; matching, the GST register and the reconciliation learn the new kind.

**Tech Stack:** Django 5 / DRF, Postgres RLS (CI only), pytest, drf-spectacular, React 19 / TanStack Query, vitest.

**Spec:** `docs/superpowers/specs/2026-10-11-bill-of-entry-design.md` (read it first). Where this plan differs from the spec, the plan is the newer, code-checked decision and Task 10 updates the spec to match: default landed-cost ledger is the existing standard ledger "Purchases" (no new standard ledger); the invoice key is port + number (the BoE number is unique per port per year, and the financial year is already in the uniqueness constraint); the foreign-flag suggestion is an open item, not a party-screen hint; the open item for an unexplained customs payment is deferred.

## Global Constraints

- Money is whole paise, `int`, never float. Rupee strings are converted once by `parseRupees` on the web.
- Never `git add -A` at the repo root (untracked `node_modules/`, `package*.json`). Stage explicit paths.
- Never `git stash`. Never force-push. **Do not push or deploy**: the user said "test locally, deploy later". Commit locally only.
- Every new tenant table needs its RLS migration as a **separate** migration using `ddl_tenant_context_operations()` + `rls_operations(table)`, `db_default` on defaulted columns, and a factory in `core/tests/factories.py` (the tenant-isolation gate fails without it).
- Exact-name exception mapping in `api/exceptions.py` `DOMAIN_ERRORS`.
- OpenAPI must be regenerated after API changes: `python manage.py spectacular --file web/openapi.yaml`, then `cd web && npm run gen:api`, or CI fails.
- There is no Postgres on this PC. Pure tests run locally (`python -X utf8 -m pytest <file> -q`); tests marked `django_db` run only in CI. Say which ran and which did not.
- Use `python -X utf8` for anything printing ₹.
- Bash heredocs with apostrophes can fail ("unexpected EOF"): write files with the Write tool or a script file.
- Raw documents are never islands: a BoE links to its document, its bank payments, its supplier invoice and its GSTR-2B row.

## Review Focus

Failure modes the spec implies that no single task's happy path covers. Each has a test in the task named in brackets.

1. **Duty-free import (BCD and SWS zero, only IGST):** must post with no landed-cost line and not be refused by the "heads need an amount" rule [Task 1, Task 3].
2. **The same BoE keyed twice, or the same number at a different port:** the first is refused as a duplicate, the second is a different document [Task 3].
3. **A BoE dated inside signed-off books:** refused in words, nothing written [Task 3].
4. **Removing a BoE that has payments:** refused unless payments are released; removing it removes the side record too, never leaves an orphan or a `ProtectedError` [Task 3].
5. **A BoE in the generic bill screens:** it must not be revisable as a purchase (that would silently drop the duty split), must count as a payable, and must not appear in the Purchases list, where a click would open a voucher page that cannot save it [Task 4, Task 9].
6. **GSTR-2B import row with no BoE booked, and a BoE booked with no 2B row yet:** the first stays "verify against the bill of entry"; the second must read "not on 2B yet", not "invalid GSTIN" [Task 5].
7. **A foreign-flagged goods purchase with no BoE near it, and a BoE with no foreign purchase near it:** one open item each, naming the document; a reverse-charge (services) import must not be flagged; a BoE assessed at a different figure from the invoice (exchange rate, CIF against FOB) must not be flagged merely for the difference [Task 6].
8. **A payment equal to the open BoE amount from a bank row whose narration says only "ICEGATE" or "CUSTOMS":** settles automatically only when exactly one bill fits [Task 4].

## File Structure

| File | Responsibility |
|---|---|
| `ledger/boe.py` (new) | `BoeError`, `BoeFigures`, `check`, `plan_boe` (pure); `customs_party`, `post_boe` (DB) |
| `ledger/foreign.py` (new) | `looks_foreign(fields)` pure rule used by one open-item detector |
| `ledger/models.py` | `BillKind.IMPORT_DUTY`, constraint widened, `BillOfEntry` |
| `ledger/billing.py` | `_KIND_RULES` entry, identity override for BoE |
| `ledger/matching.py` | payables kinds include `IMPORT_DUTY`; customs names |
| `ledger/partyreports.py` | `IMPORT_DUTY` counts as a payable |
| `ledger/openitems.py` | `boe_without_invoice`, `import_invoice_without_boe`, `party_looks_foreign` |
| `gst/books.py`, `gst/matching.py` | BoE bills become `IMPG` register rows; `reconcile` matches them to the portal `IMPG` row |
| `classify/models.py` + migration | `Party.is_foreign` |
| `api/serializers/boe.py`, `api/views/boe.py` (new) | create, list, retrieve, delete |
| `api/serializers/classify.py` | `is_foreign` on the party |
| `api/views/billing.py` | `revise` refuses a BoE |
| `web/src/features/purchases/BillOfEntryDialog.tsx` (new), `web/src/lib/vouchers.ts`, `MastersScreen.tsx` | entry dialog, labels, party checkbox |

---

### Task 1: The duty split (pure arithmetic)

**Files:**
- Create: `ledger/boe.py`
- Test: `ledger/tests/test_boe_plan.py`

**Interfaces:**
- Produces: `BoeError(ValueError)`; `BoeFigures(assessable_paise, bcd_paise=0, sws_paise=0, igst_paise=0, cess_paise=0)` with properties `landed_paise`, `total_paise`, `portal_taxable_paise`; `check(figures) -> None` raising `BoeError`; `plan_boe(landed_cost_ledger, figures) -> billing.VoucherPlan`.

- [ ] **Step 1: Write the failing tests**

Create `ledger/tests/test_boe_plan.py`:

```python
"""What a Bill of Entry posts: the duty split, as pure arithmetic."""

from __future__ import annotations

import pytest

from ledger import billing
from ledger.boe import BoeError, BoeFigures, check, plan_boe

CR, DR = billing.CR, billing.DR


def lines_of(plan):
    return [(line.ledger, line.direction, line.amount_paise) for line in plan.lines]


def test_duties_split_into_landed_cost_and_input_credit():
    figures = BoeFigures(assessable_paise=10_00_000, bcd_paise=1_00_000, sws_paise=10_000, igst_paise=2_05_800, cess_paise=5_000)

    plan = plan_boe("LANDED", figures)

    assert figures.landed_paise == 1_10_000
    assert figures.total_paise == 3_20_800
    assert figures.portal_taxable_paise == 11_10_000  # the value IGST is charged on: assessable + BCD + SWS
    assert lines_of(plan) == [
        ("LANDED", DR, 1_10_000),
        (billing.INPUT["igst"], DR, 2_05_800),
        (billing.INPUT["cess"], DR, 5_000),
        (billing.PARTY, CR, 3_20_800),
    ]
    assert plan.party_paise == 3_20_800 and plan.taxable_paise == 1_10_000
    assert plan.debits == plan.credits


def test_a_duty_free_import_with_only_igst_has_no_landed_cost_line():
    plan = plan_boe("LANDED", BoeFigures(assessable_paise=5_00_000, igst_paise=90_000))

    assert lines_of(plan) == [(billing.INPUT["igst"], DR, 90_000), (billing.PARTY, CR, 90_000)]
    assert plan.taxable_paise == 0


@pytest.mark.parametrize(
    "figures, words",
    [
        (BoeFigures(assessable_paise=0, igst_paise=100), "assessable value"),
        (BoeFigures(assessable_paise=100, bcd_paise=-1, igst_paise=100), "basic customs duty"),
        (BoeFigures(assessable_paise=100), "no duty"),
        (BoeFigures(assessable_paise=100, igst_paise=1.5), "whole number of paise"),
        (BoeFigures(assessable_paise=100, igst_paise=True), "whole number of paise"),
    ],
)
def test_figures_that_cannot_make_a_voucher_are_refused_in_words(figures, words):
    with pytest.raises(BoeError) as raised:
        check(figures)
    assert words in str(raised.value).lower() or words in str(raised.value)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest ledger/tests/test_boe_plan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ledger.boe'`.

- [ ] **Step 3: Write the minimal implementation**

Create `ledger/boe.py`:

```python
"""Import duty: what a Bill of Entry (BoE) posts to the books.

A customs payment reaches the bank statement as one number. The BoE says what it was: customs duty that becomes part of the
cost of the goods (basic duty and the social welfare surcharge), and IGST and cess that the client takes credit for. This
module holds that split as pure arithmetic (no database), and, below it, the posting that turns it into a voucher through
``ledger.billing`` so every rule that governs a bill (permission, sign-off lock, numbering, the database guards) applies.

The assessable value is *not* posted here: it is the foreign supplier's invoice, booked as an ordinary purchase. The BoE
carries it only to compute the value the portal calls "taxable" and to be checked against that invoice.
"""

from __future__ import annotations

from dataclasses import dataclass

from ledger.billing import CR, DR, INPUT, PARTY, PlannedLine, VoucherPlan, _balanced


class BoeError(ValueError):
    """The Bill of Entry cannot be booked as given. Always something a person can fix."""


@dataclass(frozen=True)
class BoeFigures:
    assessable_paise: int
    bcd_paise: int = 0
    sws_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0

    @property
    def landed_paise(self) -> int:
        """Duty that becomes part of the cost of the goods."""
        return self.bcd_paise + self.sws_paise

    @property
    def total_paise(self) -> int:
        """What Customs is owed."""
        return self.landed_paise + self.igst_paise + self.cess_paise

    @property
    def portal_taxable_paise(self) -> int:
        """The value IGST is charged on, which GSTR-2B shows as the taxable value of an import."""
        return self.assessable_paise + self.landed_paise


def check(figures: BoeFigures) -> None:
    for name, value in (
        ("The assessable value", figures.assessable_paise),
        ("Basic customs duty", figures.bcd_paise),
        ("The social welfare surcharge", figures.sws_paise),
        ("IGST", figures.igst_paise),
        ("Cess", figures.cess_paise),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BoeError(f"{name} must be a whole number of paise, zero or more.")
    if figures.assessable_paise <= 0:
        raise BoeError("The assessable value must be more than zero.")
    if figures.total_paise <= 0:
        raise BoeError("This Bill of Entry has no duty to pay, so there is nothing to book.")


def plan_boe(landed_cost_ledger, figures: BoeFigures) -> VoucherPlan:
    """``Dr`` landed cost, ``Dr`` Input IGST, ``Dr`` Input cess / ``Cr`` the Customs party.

    A duty-free import (only IGST) has no landed-cost line. The plan balances by construction.
    """
    check(figures)
    lines = []
    if figures.landed_paise:
        lines.append(PlannedLine(landed_cost_ledger, DR, figures.landed_paise))
    if figures.igst_paise:
        lines.append(PlannedLine(INPUT["igst"], DR, figures.igst_paise))
    if figures.cess_paise:
        lines.append(PlannedLine(INPUT["cess"], DR, figures.cess_paise))
    lines.append(PlannedLine(PARTY, CR, figures.total_paise))
    return _balanced(lines, figures.total_paise, figures.landed_paise)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -X utf8 -m pytest ledger/tests/test_boe_plan.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add ledger/boe.py ledger/tests/test_boe_plan.py
git commit -m "Bill of Entry: the duty split as pure arithmetic (landed cost, input IGST and cess, Customs payable)"
```

---

### Task 2: Models, migrations and the tenant factory

**Files:**
- Modify: `ledger/models.py` (BillKind, Bill constraint, new `BillOfEntry`)
- Modify: `classify/models.py` (`Party.is_foreign`)
- Create (generated, then edited): `ledger/migrations/0034_bill_of_entry.py`, `ledger/migrations/0035_bill_of_entry_security.py`, `classify/migrations/0024_party_is_foreign.py`
- Modify: `core/tests/factories.py`
- Test: `ledger/tests/test_boe_model.py`

**Interfaces:**
- Produces: `BillKind.IMPORT_DUTY`; `BillOfEntry(client, bill, port_code, boe_number, boe_date, icegate_ref_date, assessable_paise, bcd_paise, sws_paise, igst_paise, cess_paise)`; `Party.is_foreign: bool`.

- [ ] **Step 1: Write the failing test**

Create `ledger/tests/test_boe_model.py`:

```python
"""The Bill of Entry's side record and the bill kind it needs (database: runs in CI)."""

from __future__ import annotations

import datetime

import pytest
from django.db import DatabaseError, IntegrityError, transaction

from core.db.session import firm_context
from core.tests.factories import FACTORIES
from ledger.models import Bill, BillKind, BillOfEntry

pytestmark = pytest.mark.django_db


def test_a_bill_of_entry_is_a_credit_bill_and_keeps_its_side_record(firm):
    with firm_context(firm.pk):
        record = FACTORIES[BillOfEntry](firm)
        record.refresh_from_db()
        bill = record.bill

        assert bill.kind == BillKind.IMPORT_DUTY and bill.direction == "CR"
        assert bill.boe.pk == record.pk
        assert record.client_id == bill.client_id


def test_a_bill_of_entry_with_a_negative_duty_is_refused_by_the_database(firm):
    with firm_context(firm.pk):
        template = FACTORIES[BillOfEntry](firm)
        other = Bill.objects.create(
            firm=firm, client=template.client, party=template.bill.party, kind=BillKind.IMPORT_DUTY, direction="CR",
            reference="BOE-NEG", bill_date=datetime.date(2025, 6, 11), booked_on=datetime.date(2025, 6, 11),
            financial_year=2025, taxable_paise=1, total_paise=1, invoice_key="n" * 64,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            BillOfEntry.objects.create(
                firm=firm, client=template.client, bill=other, port_code="INBOM4", boe_number="1",
                boe_date=datetime.date(2025, 6, 11), assessable_paise=100, igst_paise=-1,
            )


def test_the_bill_kind_constraint_refuses_a_debit_import_bill(firm):
    # Inserted, not updated: a bill row is never updated (its trigger refuses first), so only an insert reaches the constraint.
    with firm_context(firm.pk):
        template = FACTORIES[BillOfEntry](firm)
        with pytest.raises(IntegrityError), transaction.atomic():
            Bill.objects.create(
                firm=firm, client=template.client, party=template.bill.party, kind=BillKind.IMPORT_DUTY, direction="DR",
                reference="BOE-DR", bill_date=datetime.date(2025, 6, 11), booked_on=datetime.date(2025, 6, 11),
                financial_year=2025, taxable_paise=1, total_paise=1, invoice_key="d" * 64,
            )


def test_a_bill_of_entry_record_is_never_edited(firm):
    with firm_context(firm.pk):
        record = FACTORIES[BillOfEntry](firm)
        with pytest.raises(DatabaseError), transaction.atomic():
            BillOfEntry.objects.filter(pk=record.pk).update(igst_paise=record.igst_paise + 1)
```

(`firm` is the fixture defined in the shared conftest that `api/tests/conftest.py` builds `client_record` from.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest ledger/tests/test_boe_model.py -q`
Expected: no database locally, so it errors at fixture setup; the import error `cannot import name 'BillOfEntry'` is the signal that matters. CI is the real run.

- [ ] **Step 3: Edit the models**

In `ledger/models.py`, add to `BillKind` after `OPENING`:

```python
    #: A customs Bill of Entry: the duty owed to Customs for an import, booked as a bill so payments settle it.
    IMPORT_DUTY = "IMPORT_DUTY", "Bill of Entry (customs duty)"
```

In `Bill.Meta.constraints`, replace `ck_bill_direction_matches_kind`:

```python
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["PURCHASE", "CREDIT_NOTE", "IMPORT_DUTY"], direction="CR")
                    | models.Q(kind__in=["SALES", "DEBIT_NOTE"], direction="DR")
                    | models.Q(kind="OPENING")
                ),
                name="ck_bill_direction_matches_kind",
            ),
```

Add after the `Bill` class (before `AllocationKind`):

```python
class BillOfEntry(UUIDModel, FirmScopedModel):
    """The facts of a customs Bill of Entry that a bill has no column for.

    The bill beside it carries the money: ``taxable_paise`` is basic duty plus the social welfare surcharge (what becomes
    landed cost), ``igst_paise`` and ``cess_paise`` are the credits, ``total_paise`` is what Customs is owed. This holds the
    breakdown, the assessable value (the foreign supplier's invoice, not posted here), the port and the ICEGATE date.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="bills_of_entry")
    bill = models.OneToOneField(Bill, on_delete=models.CASCADE, related_name="boe")
    port_code = models.CharField(max_length=10)
    boe_number = models.CharField(max_length=20)
    boe_date = models.DateField()
    icegate_ref_date = models.DateField(null=True, blank=True)
    assessable_paise = models.BigIntegerField()
    bcd_paise = models.BigIntegerField(default=0, db_default=0)
    sws_paise = models.BigIntegerField(default=0, db_default=0)
    igst_paise = models.BigIntegerField(default=0, db_default=0)
    cess_paise = models.BigIntegerField(default=0, db_default=0)

    class Meta:
        db_table = "ledger_bill_of_entry"
        ordering = ["-boe_date", "boe_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(assessable_paise__gt=0, bcd_paise__gte=0, sws_paise__gte=0, igst_paise__gte=0, cess_paise__gte=0),
                name="ck_boe_amounts",
            ),
        ]
        indexes = [models.Index(fields=["firm", "client", "boe_date"], name="idx_boe_client_date")]

    def __str__(self) -> str:
        return f"BoE {self.boe_number} ({self.port_code})"
```

In `classify/models.py`, after the `msme` field of `Party`:

```python
    #: The supplier is outside India, so what it sends in is an import. Set by a person, never guessed; it is what lets the books
    #: ask "this import has no Bill of Entry". Not the same as having no GSTIN (an unregistered Indian supplier has none either).
    is_foreign = models.BooleanField(default=False, db_default=False)
```

- [ ] **Step 4: Generate and edit the migrations**

Run: `python manage.py makemigrations ledger classify -n bill_of_entry`
Then rename and fix so the files are exactly:
- `classify/migrations/0024_party_is_foreign.py` (an `AddField` for `is_foreign`; rename the generated classify file to this name and make sure `dependencies = [("classify", "0023_msme_and_note_section")]`).
- `ledger/migrations/0034_bill_of_entry.py`: `AlterField` of `Bill.kind` choices, `RemoveConstraint`/`AddConstraint` for `ck_bill_direction_matches_kind`, `CreateModel BillOfEntry`. Prepend `*ddl_tenant_context_operations()` as `0032_stock_items.py` does, with `from core.db.rls import ddl_tenant_context_operations`. Its dependencies must include `("ledger", "0033_stock_items_security")` and the classify and core migrations the generator names.

Create `ledger/migrations/0035_bill_of_entry_security.py`:

```python
"""Row-level security for Bills of Entry, and the rules the books keep for them in the database.

A Bill of Entry's figures must agree with the bill beside it, so they are never edited (the bill is never edited either);
the record is removed only with its bill, and not from signed-off books; and it belongs to the same client as its bill.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

GUARD = """
CREATE OR REPLACE FUNCTION app.ledger_bill_of_entry_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    locked_through date;
    bill_day       date;
    bill_client    uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.client_id, NEW.bill_id, NEW.port_code, NEW.boe_number, NEW.boe_date, NEW.assessable_paise,
               NEW.bcd_paise, NEW.sws_paise, NEW.igst_paise, NEW.cess_paise)
           IS DISTINCT FROM
           ROW(OLD.client_id, OLD.bill_id, OLD.port_code, OLD.boe_number, OLD.boe_date, OLD.assessable_paise,
               OLD.bcd_paise, OLD.sws_paise, OLD.igst_paise, OLD.cess_paise) THEN
            RAISE EXCEPTION 'a Bill of Entry is never edited'
                USING ERRCODE = '42501',
                      HINT = 'Remove it and enter it again, before the books are signed off.';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        SELECT signed_off_through INTO locked_through FROM core_client WHERE id = OLD.client_id;
        SELECT booked_on INTO bill_day FROM ledger_bill WHERE id = OLD.bill_id;
        IF bill_day IS NOT NULL AND locked_through IS NOT NULL AND bill_day <= locked_through THEN
            RAISE EXCEPTION 'this Bill of Entry is dated %, inside books signed off through %', bill_day, locked_through
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;

    SELECT client_id INTO bill_client FROM ledger_bill WHERE id = NEW.bill_id;
    IF bill_client IS DISTINCT FROM NEW.client_id THEN
        RAISE EXCEPTION 'a Bill of Entry and its bill must belong to the same client' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_bill_of_entry_guard ON ledger_bill_of_entry;
CREATE TRIGGER ledger_bill_of_entry_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_bill_of_entry
    FOR EACH ROW EXECUTE FUNCTION app.ledger_bill_of_entry_guard();
"""

DROP = """
DROP TRIGGER IF EXISTS ledger_bill_of_entry_guard ON ledger_bill_of_entry;
DROP FUNCTION IF EXISTS app.ledger_bill_of_entry_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0034_bill_of_entry")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_bill_of_entry"),
        migrations.RunSQL(GUARD, reverse_sql=DROP),
    ]
```
- [ ] **Step 5: Add the factory**

In `core/tests/factories.py` add `BillOfEntry` to the `ledger.models` import and, near `_bill`:

```python
def _bill_of_entry(firm, **kw):
    client = kw.get("client") or _client(firm)
    party = kw.get("party") or _party(firm, client=client)
    bill = Bill.objects.create(
        firm=firm,
        client=client,
        party=party,
        kind=BillKind.IMPORT_DUTY,
        direction=Direction.CREDIT,
        reference=f"BOE-{uuid.uuid4().hex[:8]}",
        bill_date=datetime.date(2025, 6, 10),
        booked_on=datetime.date(2025, 6, 10),
        financial_year=2025,
        taxable_paise=1_00_000,
        igst_paise=2_00_000,
        total_paise=3_00_000,
        invoice_key=uuid.uuid4().hex * 2,
    )
    return BillOfEntry.objects.create(
        firm=firm, client=client, bill=bill, port_code="INBOM4", boe_number="1234567", boe_date=datetime.date(2025, 6, 10),
        assessable_paise=10_00_000, bcd_paise=1_00_000, igst_paise=2_00_000,
    )
```

and in the `FACTORIES` dict: `BillOfEntry: _bill_of_entry,`.

- [ ] **Step 6: Check migrations are consistent**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.
Run: `python -X utf8 -m pytest core/tests/test_migration_compat.py -q` (if it needs no DB; otherwise note it runs in CI).

- [ ] **Step 7: Commit**

```bash
git add ledger/models.py classify/models.py ledger/migrations/0034_bill_of_entry.py ledger/migrations/0035_bill_of_entry_security.py classify/migrations/0024_party_is_foreign.py core/tests/factories.py ledger/tests/test_boe_model.py
git commit -m "Bill of Entry: bill kind IMPORT_DUTY, BillOfEntry side record with RLS, foreign flag on parties"
```

---

### Task 3: Booking and removing a Bill of Entry

**Files:**
- Modify: `ledger/billing.py` (`_KIND_RULES`, the key identity in `_post`)
- Modify: `ledger/boe.py` (add `customs_party`, `post_boe`)
- Modify: `api/exceptions.py` (map `BoeError`)
- Test: `api/tests/test_boe.py` (service-level DB tests; API tests are added in Task 8)

**Interfaces:**
- Consumes: Task 1 `BoeFigures`, `plan_boe`, `BoeError`; Task 2 `BillOfEntry`, `BillKind.IMPORT_DUTY`.
- Produces: `customs_party(client, port_code) -> Party`; `post_boe(client, *, port_code, boe_number, boe_date, figures, membership, landed_cost_ledger=None, icegate_ref_date=None, own_gstin="", document=None, narration="") -> Bill`. Removal is `billing.remove_bill(bill, ...)` unchanged (the side record cascades).

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_boe.py`:

```python
"""Bill of Entry: booked as a bill, settled by ordinary payments, removed with its side record (database: CI only)."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_bills import V1, base, make_ledger  # noqa: F401  (fixtures and helpers)
from core.db.session import firm_context
from ledger import billing, boe
from ledger.models import Bill, BillKind, BillOfEntry, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

FIGURES = boe.BoeFigures(assessable_paise=10_00_000, bcd_paise=1_00_000, sws_paise=10_000, igst_paise=2_05_800)


def book(client_record, membership, **over):
    args = dict(
        port_code="INBOM4", boe_number="2345678", boe_date=datetime.date(2025, 6, 10), figures=FIGURES,
        membership=membership,
    )
    args.update(over)
    return boe.post_boe(client_record, **args)


def test_a_bill_of_entry_posts_the_duties_in_one_voucher(client_record, senior):
    with firm_context(client_record.firm_id):
        bill = book(client_record, senior)

        assert bill.kind == BillKind.IMPORT_DUTY and bill.direction == "CR"
        assert bill.taxable_paise == 1_10_000 and bill.igst_paise == 2_05_800 and bill.total_paise == 3_15_800
        assert bill.party.canonical_name == "Customs (INBOM4)"
        lines = sorted(
            (line.ledger_account.name, line.direction, line.amount_paise) for line in bill.entry.lines.all()
        )
        assert lines == [
            ("Customs (INBOM4)", "CR", 3_15_800),
            ("Input IGST", "DR", 2_05_800),
            ("Purchases", "DR", 1_10_000),
        ]
        record = bill.boe
        assert (record.port_code, record.boe_number, record.assessable_paise) == ("INBOM4", "2345678", 10_00_000)
        assert billing.open_amount(bill) == 3_15_800


def test_the_same_number_at_the_same_port_is_a_duplicate_but_another_port_is_not(client_record, senior):
    with firm_context(client_record.firm_id):
        book(client_record, senior)
        with pytest.raises(billing.BillingError):
            book(client_record, senior)
        other = book(client_record, senior, port_code="INMAA1")
        assert other.party.canonical_name == "Customs (INMAA1)"


def test_a_duty_free_import_books_only_the_input_credit(client_record, senior):
    with firm_context(client_record.firm_id):
        bill = book(client_record, senior, figures=boe.BoeFigures(assessable_paise=5_00_000, igst_paise=90_000))
        assert bill.taxable_paise == 0
        assert sorted((line.ledger_account.name, line.amount_paise) for line in bill.entry.lines.all()) == [
            ("Customs (INBOM4)", 90_000),
            ("Input IGST", 90_000),
        ]


def test_a_bill_of_entry_inside_signed_off_books_is_refused_and_writes_nothing(client_record, senior):
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 6, 30))
    client_record.refresh_from_db()
    with firm_context(client_record.firm_id):
        with pytest.raises(billing.BillingError):
            book(client_record, senior)
        assert not BillOfEntry.objects.filter(client=client_record).exists()
        assert not JournalEntry.objects.filter(client=client_record).exists()


def test_malformed_port_and_number_are_refused_in_words(client_record, senior):
    with firm_context(client_record.firm_id):
        with pytest.raises(boe.BoeError, match="port code"):
            book(client_record, senior, port_code="in bom")
        with pytest.raises(boe.BoeError, match="number"):
            book(client_record, senior, boe_number="")


def test_removing_a_bill_of_entry_removes_its_side_record_and_voucher(client_record, senior):
    with firm_context(client_record.firm_id):
        bill = book(client_record, senior)
        billing.remove_bill(bill, membership=senior)

        assert not Bill.objects.filter(pk=bill.pk).exists()
        assert not BillOfEntry.objects.filter(client=client_record).exists()
```

(`senior` is the membership fixture the service-level tests in `ledger/tests/test_ai_workflow.py` pass as `membership=`; the `api` fixture is built on it.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest api/tests/test_boe.py -q`
Expected: locally an error at setup (no database) or `AttributeError: module 'ledger.boe' has no attribute 'post_boe'`. The attribute error is the signal; the real run is CI.

- [ ] **Step 3: Change `billing._post` to accept the BoE kind**

In `ledger/billing.py`, add to `_KIND_RULES`:

```python
    #: A customs Bill of Entry is a journal: the duty owed to Customs, not a supplier's invoice.
    BillKind.IMPORT_DUTY: (VoucherType.JOURNAL, CR, (PartyRole.VENDOR, PartyRole.BOTH), LedgerGroup.CREDITOR),
```

In `_post`, replace the `identity = ... if kind in (...) else (...)` expression with:

```python
    if kind == BillKind.IMPORT_DUTY:
        # A Bill of Entry is identified by its port and number, not by a supplier GSTIN (``ledger.boe`` sets this).
        identity = data.extra["identity"]
    elif kind in (BillKind.PURCHASE, BillKind.DEBIT_NOTE):
        identity = supplier_identity(party.gstin, party.pk)
    else:
        identity = supplier_identity(data.own_gstin, client.pk)
```

- [ ] **Step 4: Add the posting service**

Append to `ledger/boe.py` (add the imports at the top of the file with the others):

```python
import re

from django.db import transaction

from classify.models import Party, PartyRole
from ledger import billing
from ledger.billing import BillInput
from ledger.models import Bill, BillKind, BillOfEntry

_PORT = re.compile(r"^[A-Z0-9]{3,10}$")
_NUMBER = re.compile(r"^[A-Z0-9/-]{1,20}$")


def customs_party(client, port_code: str) -> Party:
    """The supplier account that Customs at this port is owed through, opened the first time it is used."""
    name = f"Customs ({port_code})"
    party, _ = Party.objects.get_or_create(
        firm_id=client.firm_id, client=client, canonical_name=name, defaults={"role": PartyRole.VENDOR}
    )
    if party.role not in (PartyRole.VENDOR, PartyRole.BOTH):
        raise BoeError(f"{name!r} exists as a customer. Rename it or change its role first.")
    return party


@transaction.atomic
def post_boe(
    client,
    *,
    port_code: str,
    boe_number: str,
    boe_date,
    figures: BoeFigures,
    membership,
    landed_cost_ledger=None,
    icegate_ref_date=None,
    own_gstin: str = "",
    document=None,
    narration: str = "",
) -> Bill:
    """Book a Bill of Entry: the duties as one journal, the bill owed to Customs, and its side record, or nothing."""
    port = (port_code or "").strip().upper()
    number = (boe_number or "").strip().upper()
    if not _PORT.match(port):
        raise BoeError("The port code is 3 to 10 letters or digits, like INBOM4.")
    if not _NUMBER.match(number):
        raise BoeError("Give the Bill of Entry number: up to 20 letters, digits, / or -.")
    check(figures)

    ledger = landed_cost_ledger or billing.standard_ledger(client, "Purchases")
    plan = plan_boe(ledger, figures)
    party = customs_party(client, port)
    bill = billing._post(
        client,
        party,
        BillKind.IMPORT_DUTY,
        plan,
        BillInput(
            reference=number,
            bill_date=boe_date,
            narration=narration.strip() or f"Being customs duty on Bill of Entry {number} ({port}) dated {boe_date:%d-%m-%Y}",
            document=document,
            own_gstin=own_gstin,
            igst=figures.igst_paise,
            cess=figures.cess_paise,
            extra={"identity": f"BOE:{port}"},
        ),
        membership=membership,
    )
    BillOfEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        bill=bill,
        port_code=port,
        boe_number=number,
        boe_date=boe_date,
        icegate_ref_date=icegate_ref_date,
        assessable_paise=figures.assessable_paise,
        bcd_paise=figures.bcd_paise,
        sws_paise=figures.sws_paise,
        igst_paise=figures.igst_paise,
        cess_paise=figures.cess_paise,
    )
    return bill
```

- [ ] **Step 5: Map the error**

In `api/exceptions.py` `DOMAIN_ERRORS`, after `"RectifyError"`:

```python
    "BoeError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "boe_rule"),
```

- [ ] **Step 6: Run what can run locally**

Run: `python -X utf8 -m pytest ledger/tests/test_boe_plan.py -q`
Expected: PASS. Run: `python -X utf8 -c "import ledger.boe, ledger.billing"` — no import cycle.
`api/tests/test_boe.py` runs in CI.

- [ ] **Step 7: Commit**

```bash
git add ledger/billing.py ledger/boe.py api/exceptions.py api/tests/test_boe.py
git commit -m "Bill of Entry: book the duties as one voucher owed to a Customs party; removed with the bill"
```

---

### Task 4: Payments settle a Bill of Entry; it counts as a payable

**Files:**
- Modify: `ledger/matching.py`
- Modify: `ledger/partyreports.py`
- Modify: `api/views/billing.py` (`revise` refuses a BoE)
- Test: `ledger/tests/test_matching_boe.py` (pure), `api/tests/test_boe.py` (add DB tests)

**Interfaces:**
- Consumes: Task 3 `post_boe`.
- Produces: `matching.MATCHABLE`, `matching.PAYABLE_KINDS`, `matching._names_for(bill)`.

- [ ] **Step 1: Write the failing pure test**

Create `ledger/tests/test_matching_boe.py`:

```python
"""A customs payment narrated only with ICEGATE or CUSTOMS is still recognised as the Bill of Entry's payment."""

from __future__ import annotations

from types import SimpleNamespace

from ledger import matching
from ledger.models import BillKind


def bill(kind, name="Customs (INBOM4)"):
    party = SimpleNamespace(canonical_name=name, firm_id=None)
    return SimpleNamespace(kind=kind, party=party)


def test_an_import_duty_bill_is_paid_with_money_out():
    assert matching._field(bill(BillKind.IMPORT_DUTY)) == "debit_paise"
    assert matching._field(bill(BillKind.PURCHASE)) == "debit_paise"
    assert matching._field(bill(BillKind.SALES)) == "credit_paise"


def test_customs_bills_are_matchable_and_payable():
    assert BillKind.IMPORT_DUTY in matching.MATCHABLE
    assert BillKind.IMPORT_DUTY in matching.PAYABLE_KINDS
    assert BillKind.SALES in matching.MATCHABLE and BillKind.SALES not in matching.PAYABLE_KINDS


def test_a_customs_bill_also_answers_to_icegate_and_customs():
    extra = matching.CUSTOMS_WORDS
    assert "ICEGATE" in extra and "CUSTOMS" in extra
    assert matching._says("NEFT ICEGATE DUTY PAYMENT 99887", list(extra))
    assert not matching._says("NEFT RAVI TRADERS", list(extra))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest ledger/tests/test_matching_boe.py -q`
Expected: FAIL with `AttributeError: module 'ledger.matching' has no attribute 'MATCHABLE'`.

- [ ] **Step 3: Edit `ledger/matching.py`**

Below `DAYS_AFTER = 150` add:

```python
#: The bills a bank payment can settle by itself. A Bill of Entry is paid by money out, like a purchase.
PAYABLE_KINDS = (BillKind.PURCHASE, BillKind.IMPORT_DUTY)
MATCHABLE = (BillKind.PURCHASE, BillKind.IMPORT_DUTY, BillKind.SALES)
#: What a customs payment's narration usually says instead of the party's name.
CUSTOMS_WORDS = ("CUSTOMS", "ICEGATE")
```

Replace `_field`:

```python
def _field(bill: Bill) -> str:
    """The statement column a bill's payment sits in: money out pays a purchase or customs duty, money in pays a sale."""
    return "debit_paise" if bill.kind in PAYABLE_KINDS else "credit_paise"
```

Add after `_names_of`:

```python
def _names_for(bill: Bill) -> list[str]:
    """The names a bank narration may use for whoever this bill is owed to."""
    names = _names_of(bill.party)
    return names + list(CUSTOMS_WORDS) if bill.kind == BillKind.IMPORT_DUTY else names
```

In `_rows_for`, change `bill.kind not in (BillKind.PURCHASE, BillKind.SALES)` to `bill.kind not in MATCHABLE`. In `_open_bills`, change `kind__in=(BillKind.PURCHASE, BillKind.SALES)` to `kind__in=MATCHABLE` and update the docstring ("purchase, customs and sales bills"). In `match_client` replace `names = {b.party_id: _names_of(b.party) for b in bills}` / `by_bill = {...}` with:

```python
    by_bill = {b.pk: _rows_for(b, _names_for(b)) for b in bills}
```

In `match_bill`, replace `names = _names_of(bill.party)` with `names = _names_for(bill)`, and in the loop `_rows_for(other, _names_of(other.party))` with `_rows_for(other, _names_for(other))`.

- [ ] **Step 4: Edit `ledger/partyreports.py`**

In `_SIDES[PAYABLES]["kinds"]` use `(BillKind.PURCHASE, BillKind.DEBIT_NOTE, BillKind.IMPORT_DUTY)`.

- [ ] **Step 5: Make `revise` refuse a Bill of Entry**

In `api/views/billing.py` `BillViewSet.revise`, immediately after `bill = self.get_object()`:

```python
        if bill.kind == BillKind.IMPORT_DUTY:
            raise serializers.ValidationError(
                {"detail": "A Bill of Entry is changed by removing it and entering it again, so its duty split is kept."}
            )
```

- [ ] **Step 6: Add DB tests**

Append to `api/tests/test_boe.py`:

```python
def test_a_part_payment_leaves_an_open_balance(client_record, senior):
    from django.utils import timezone

    from ledger.models import Direction, JournalLine

    with firm_context(client_record.firm_id):
        bill = book(client_record, senior)
        entry = JournalEntry.objects.create(
            firm_id=client_record.firm_id, client=client_record, entry_no=900, financial_year=2025,
            entry_date=datetime.date(2025, 6, 12), voucher_type="Payment", approved_at=timezone.now(),
        )
        line = JournalLine.build(
            entry=entry, ledger_account=bill.party.ledger, party=bill.party, direction=Direction.DEBIT, amount_paise=1_00_000
        )
        JournalLine.objects.bulk_create([line])

        billing.allocate(line, amount_paise=1_00_000, bill=bill)

        assert billing.open_amount(bill) == 2_15_800


def test_a_bill_of_entry_cannot_be_revised_as_a_purchase(api, client_record, senior):
    with firm_context(client_record.firm_id):
        bill = book(client_record, senior)

    response = api.post(f"{base(client_record)}/bills/{bill.pk}/revise/", {}, format="json")

    assert response.status_code == 400
    assert "Bill of Entry" in response.content.decode()
```

- [ ] **Step 7: Run what can run locally**

Run: `python -X utf8 -m pytest ledger/tests/test_matching_boe.py ledger/tests/test_boe_plan.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ledger/matching.py ledger/partyreports.py api/views/billing.py ledger/tests/test_matching_boe.py api/tests/test_boe.py
git commit -m "Bill of Entry: customs payments settle it like a purchase, it counts as a payable, generic revise refuses it"
```

---

### Task 5: GST — a Bill of Entry ties to the GSTR-2B import row

**Files:**
- Modify: `gst/books.py`
- Modify: `gst/matching.py` (`reconcile`)
- Test: `gst/tests/test_matching_impg.py` (pure)

**Interfaces:**
- Consumes: `BillKind.IMPORT_DUTY`, `Bill.boe` (`BillOfEntry`).
- Produces: book rows with `section=Section.IMPG`, `gstin=""`, `invoice_no=<BoE number>`, `taxable_paise=boe.portal_taxable`; `reconcile` pairs them with portal `IMPG` rows on the normalised number.

- [ ] **Step 1: Write the failing test**

Create `gst/tests/test_matching_impg.py`:

```python
"""A Bill of Entry in the books is matched to the import row GSTR-2B shows for it."""

from __future__ import annotations

import datetime

from gst.matching import Invoice, MatchKind, Section, reconcile

JUNE = datetime.date(2025, 6, 1)
ON = datetime.date(2025, 6, 10)


def book(no="2345678", igst=2_05_800, taxable=11_10_000):
    return Invoice(ref="b1", gstin="", invoice_no=no, invoice_date=ON, taxable_paise=taxable, igst_paise=igst,
                   section=Section.IMPG, supplier_name="Customs (INBOM4)")


def portal(no="2345678", igst=2_05_800, taxable=11_10_000):
    return Invoice(ref="p1", gstin="", invoice_no=no, invoice_date=ON, taxable_paise=taxable, igst_paise=igst,
                   section=Section.IMPG, supplier_name="Port INBOM4")


def kinds(result):
    return [m.kind for m in result.matches]


def test_a_booked_bill_of_entry_matches_the_portal_import_row():
    result = reconcile([book()], [portal()], period_start=JUNE)

    assert kinds(result) == [MatchKind.MATCHED]
    assert result.matches[0].eligible_paise == 2_05_800


def test_a_different_igst_is_an_amount_mismatch_not_an_invalid_gstin():
    result = reconcile([book(igst=2_00_000)], [portal()], period_start=JUNE)

    assert kinds(result) == [MatchKind.AMOUNT_MISMATCH]


def test_a_portal_import_row_with_no_bill_of_entry_still_asks_to_be_verified():
    result = reconcile([], [portal()], period_start=JUNE)

    assert kinds(result) == [MatchKind.IMPORT]


def test_a_booked_bill_of_entry_not_yet_on_the_portal_is_not_an_invalid_gstin():
    result = reconcile([book()], [], period_start=JUNE)

    assert MatchKind.INVALID_GSTIN not in kinds(result)
    assert kinds(result) == [MatchKind.MISSING_IN_2B]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest gst/tests/test_matching_impg.py -q`
Expected: FAIL (the book row is reported `INVALID_GSTIN`, and the portal row `IMPORT`).

- [ ] **Step 3: Edit `reconcile` in `gst/matching.py`**

Before the `for p in portal_rows:` loop add:

```python
    # An import is keyed by its Bill of Entry number (the portal gives no supplier GSTIN for it). When the books hold that
    # Bill of Entry, its portal row is matched to it like any invoice; otherwise it stays a row to verify.
    booked_imports = {
        (normalise_gstin(b.gstin), normalise_invoice_no(b.invoice_no)) for b in book_rows if b.section is Section.IMPG
    }
```

Change the portal loop's first branch to:

```python
        if p.section is Section.ISD or (p.section is Section.IMPG and p.key not in booked_imports):
            matches.append(_portal_credit(p))
            continue
```

In the book loop, change the invalid-GSTIN guard to leave imports alone:

```python
        if b.section is not Section.IMPG and (not gstin or not is_valid_gstin(gstin)):
```

(Keep the body of that `if` exactly as it is; only its condition changes.) Everything after — duplicate, claimed-elsewhere, differences, ITC, missing-in-2B — then applies to the import as to any invoice.

Compare an import on its tax heads only. What GSTR-2B puts in an import's taxable value (assessable value, or assessable plus duty) is not something the books can be sure of without a real file, and the credit, not the base, is what a person claims. In `_differences`, replace the head list:

```python
def _differences(book: Invoice, portal: Invoice) -> dict[str, int]:
    """Heads where the two differ by more than the rounding tolerance. An import is compared on its tax heads only."""
    heads = TAX_HEADS if book.section is Section.IMPG else ("taxable_paise", *TAX_HEADS)
    diffs = {}
    for head in heads:
        delta = getattr(book, head) - getattr(portal, head)
        if abs(delta) > TOLERANCE_PAISE:
            diffs[head] = delta
    return diffs
```

And add one more test to `gst/tests/test_matching_impg.py` (written in Step 1 above, so it fails first with the rest):

```python
def test_a_different_taxable_value_alone_does_not_stop_an_import_matching():
    result = reconcile([book(taxable=10_00_000)], [portal(taxable=11_10_000)], period_start=JUNE)

    assert kinds(result) == [MatchKind.MATCHED]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -X utf8 -m pytest gst/tests/test_matching_impg.py gst/tests/test_matching.py -q`
Expected: PASS; the existing 2B matching tests still pass. If an existing test asserts that an IMPG portal row is always `IMPORT`, it must still hold because `booked_imports` is empty there.

- [ ] **Step 5: Emit Bills of Entry from the books**

In `gst/books.py` `load_register_from_books`:

```python
    kinds = Q(kind__in=[BillKind.PURCHASE, BillKind.DEBIT_NOTE, BillKind.IMPORT_DUTY])
    base = (
        Bill.objects.filter(firm_id=run.firm_id, client=run.client)
        .filter(month, kinds)
        .select_related("party", "boe")
    )
```

and in the row-building loop replace the `section=` and the amounts so an import is emitted as the portal shows it:

```python
        is_import = bill.kind == BillKind.IMPORT_DUTY
        row = RegisterInvoice(
            firm_id=run.firm_id,
            run=run,
            invoice_no=bill.reference[:64],
            invoice_date=bill.bill_date,
            supplier_name=bill.party.canonical_name[:255],
            section=(
                Section.IMPG if is_import else Section.CDN if bill.kind == BillKind.DEBIT_NOTE else Section.B2B
            ).value,
            taxable_paise=(
                bill.boe.assessable_paise + bill.boe.bcd_paise + bill.boe.sws_paise if is_import else bill.taxable_paise
            ),
            igst_paise=bill.igst_paise,
            cgst_paise=bill.cgst_paise,
            sgst_paise=bill.sgst_paise,
            cess_paise=bill.cess_paise,
            source_row=position,
            rcm=bill.rcm,
        )
        row.set_gstin("" if is_import else bill.party.gstin)
```

Update the module docstring's first paragraph to mention that a Bill of Entry becomes an import row.

- [ ] **Step 6: Run and commit**

Run: `python -X utf8 -m pytest gst/tests -q -k "not django_db"` (the DB-backed ones run in CI).
Expected: pure tests PASS.

```bash
git add gst/books.py gst/matching.py gst/tests/test_matching_impg.py
git commit -m "GST: a booked Bill of Entry is matched to its GSTR-2B import row instead of waiting to be verified"
```

---

### Task 6: Open items for the gaps, and the foreign suggestion

**Files:**
- Create: `ledger/foreign.py`
- Modify: `ledger/openitems.py`
- Test: `ledger/tests/test_foreign_pure.py` (pure), `api/tests/test_boe.py` (DB detector tests)

**Interfaces:**
- Produces: `foreign.looks_foreign(fields: dict) -> bool`; detectors `boe_without_invoice`, `import_invoice_without_boe`, `party_looks_foreign`.

- [ ] **Step 1: Write the failing pure test**

Create `ledger/tests/test_foreign_pure.py`:

```python
from __future__ import annotations

import pytest

from ledger.foreign import looks_foreign


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"currency": "USD", "supplier_gstin": ""}, True),
        ({"currency": "usd", "supplier_gstin": ""}, True),
        ({"currency": "USD", "supplier_gstin": "27ABCDE1234F1Z5"}, False),  # a registered Indian supplier billing in dollars
        ({"currency": "INR", "supplier_gstin": ""}, False),
        ({"currency": "", "supplier_gstin": ""}, False),
        ({}, False),
    ],
)
def test_a_foreign_currency_and_no_gstin_looks_foreign(fields, expected):
    assert looks_foreign(fields) is expected
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -X utf8 -m pytest ledger/tests/test_foreign_pure.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ledger.foreign'`.

- [ ] **Step 3: Implement**

Create `ledger/foreign.py`:

```python
"""Whether an invoice reading looks like it is from a supplier outside India. A hint only; a person sets the party's flag."""

from __future__ import annotations


def looks_foreign(fields: dict) -> bool:
    """A currency other than rupees and no GSTIN for the supplier."""
    currency = str(fields.get("currency") or "").strip().upper()
    gstin = str(fields.get("supplier_gstin") or "").strip()
    return bool(currency) and currency != "INR" and not gstin
```

- [ ] **Step 4: Add the detectors**

In `ledger/openitems.py`, after `purchases_not_in_the_register`:

```python
#: How far apart a Bill of Entry and the supplier invoice it was paid on may be dated. The two are never the same figure (the
#: assessed value is converted at Customs' own rate and may be CIF where the invoice is FOB), so they are paired by supplier
#: and by date, not by amount.
BOE_WINDOW_DAYS = 60


def _foreign_goods_purchases(client):
    """Purchases from a party marked foreign that put something on a goods ledger. Reverse charge ones are services."""
    from classify.models import LedgerGroup

    goods = [LedgerGroup.PURCHASE, LedgerGroup.DIRECT_EXPENSE, LedgerGroup.FIXED_ASSET]
    return (
        Bill.objects.filter(
            firm_id=client.firm_id,
            client=client,
            kind=BillKind.PURCHASE,
            party__is_foreign=True,
            rcm=False,
            entry__lines__ledger_account__group__in=goods,
        )
        .distinct()
        .select_related("party")
    )


@detector("boe_without_invoice", "A Bill of Entry with no foreign purchase booked near it")
def bills_of_entry_without_an_invoice(client):
    """The duty is booked but no purchase of goods from a foreign supplier is booked within weeks of it."""
    import datetime

    from ledger.models import BillOfEntry

    window = datetime.timedelta(days=BOE_WINDOW_DAYS)
    dates = [bill.bill_date for bill in _foreign_goods_purchases(client)]
    for record in BillOfEntry.objects.filter(firm_id=client.firm_id, client=client):
        if any(abs(date - record.boe_date) <= window for date in dates):
            continue
        yield OpenItem(
            kind="boe_without_invoice",
            client_id=client.pk,
            summary=(
                f"Bill of Entry {record.boe_number} ({record.port_code}) of {record.boe_date:%d-%m-%Y} has no purchase of "
                f"goods from a foreign supplier booked near it, so the goods it was paid on are not in the books."
            ),
            amount_paise=record.assessable_paise,
            since=record.boe_date,
            link={"type": "bill", "id": str(record.bill_id)},
        )


@detector("import_invoice_without_boe", "An import invoice with no Bill of Entry")
def import_invoices_without_a_bill_of_entry(client):
    """A purchase of goods from a foreign supplier with no Bill of Entry booked within weeks of it.

    Services are left out: an import of services is booked under reverse charge and has no Bill of Entry.
    """
    import datetime

    from ledger.models import BillOfEntry

    window = datetime.timedelta(days=BOE_WINDOW_DAYS)
    dates = list(BillOfEntry.objects.filter(firm_id=client.firm_id, client=client).values_list("boe_date", flat=True))
    for bill in _foreign_goods_purchases(client):
        if any(abs(date - bill.bill_date) <= window for date in dates):
            continue
        yield OpenItem(
            kind="import_invoice_without_boe",
            client_id=client.pk,
            summary=(
                f"{bill.party.canonical_name}'s invoice {bill.reference} for goods has no Bill of Entry booked near "
                f"{bill.bill_date:%d-%m-%Y}, so the customs duty and the IGST credit on it are not in the books."
            ),
            amount_paise=bill.total_paise,
            since=bill.bill_date,
            link={"type": "bill", "id": str(bill.pk)},
        )


@detector("party_looks_foreign", "A supplier that looks foreign but is not marked as one")
def parties_that_look_foreign(client):
    """Said once: marking the party foreign (or leaving it) is a person's call, so this only points at it."""
    from ledger import invoice_intake
    from ledger.foreign import looks_foreign
    from ledger.models import InvoiceReading, ReadingStatus

    seen = set()
    readings = InvoiceReading.objects.filter(
        firm_id=client.firm_id, client=client, status=ReadingStatus.BOOKED, bill__party__is_foreign=False
    ).select_related("bill__party")
    for reading in readings:
        party = reading.bill.party
        if party.pk in seen or not looks_foreign(invoice_intake.fields_of(reading)):
            continue
        seen.add(party.pk)
        yield OpenItem(
            kind="party_looks_foreign",
            client_id=client.pk,
            summary=(
                f"{party.canonical_name}'s invoice {reading.bill.reference} is not in rupees and has no GSTIN. "
                f"If they are a foreign supplier, mark them as foreign on the Parties screen."
            ),
            amount_paise=0,
            since=reading.bill.bill_date,
            link={"type": "bill", "id": str(reading.bill_id)},
        )
```

Make sure `BillKind` and `format_inr` are imported at the top of `ledger/openitems.py` (they are used by the existing detectors; add only what is missing).

- [ ] **Step 5: Add DB detector tests**

Append to `api/tests/test_boe.py`:

```python
def test_a_bill_of_entry_with_no_foreign_purchase_near_it_is_an_open_item(client_record, senior):
    from ledger import openitems

    with firm_context(client_record.firm_id):
        book(client_record, senior)
        kinds = [item.kind for item in openitems.open_items(client_record)]
        assert "boe_without_invoice" in kinds


def test_a_foreign_goods_purchase_near_the_bill_of_entry_clears_both_items(api, client_record, senior):
    from api.tests.test_bills import make_party, post_bill, voucher
    from classify.models import Party
    from ledger import openitems

    supplier = make_party(api, client_record, name="Shenzhen Parts Ltd", gstin="")
    purchases = make_ledger(api, client_record, "Import purchases", "PURCHASE")
    with firm_context(client_record.firm_id):
        Party.objects.filter(pk=supplier["id"]).update(is_foreign=True)
        book(client_record, senior)
    # Booked at a different figure from the assessed value, three weeks earlier, as it would be in practice.
    posted = post_bill(
        api,
        client_record,
        voucher(
            supplier, purchases, bill_date="2025-05-20", cgst_paise=0, sgst_paise=0,
            heads=[{"ledger": purchases["id"], "amount_paise": 9_00_000}],
        ),
    )
    assert posted.status_code == 201, posted.content

    with firm_context(client_record.firm_id):
        kinds = [item.kind for item in openitems.open_items(client_record)]
    assert "boe_without_invoice" not in kinds and "import_invoice_without_boe" not in kinds


def test_a_reverse_charge_import_is_a_service_and_is_not_asked_for_a_bill_of_entry(api, client_record):
    from api.tests.test_bills import make_party, post_bill, voucher
    from classify.models import Party
    from ledger import openitems

    supplier = make_party(api, client_record, name="Cloud Services Inc", gstin="")
    purchases = make_ledger(api, client_record, "Import purchases", "PURCHASE")
    with firm_context(client_record.firm_id):
        Party.objects.filter(pk=supplier["id"]).update(is_foreign=True)
    posted = post_bill(
        api, client_record, voucher(supplier, purchases, bill_date="2025-05-20", cgst_paise=0, sgst_paise=0, igst_paise=90_000, rcm=True)
    )
    assert posted.status_code == 201, posted.content

    with firm_context(client_record.firm_id):
        kinds = [item.kind for item in openitems.open_items(client_record)]
    assert "import_invoice_without_boe" not in kinds
```

- [ ] **Step 6: Run and commit**

Run: `python -X utf8 -m pytest ledger/tests/test_foreign_pure.py -q`
Expected: PASS.

```bash
git add ledger/foreign.py ledger/openitems.py ledger/tests/test_foreign_pure.py api/tests/test_boe.py
git commit -m "Open items: a Bill of Entry with no supplier invoice, an import invoice with no Bill of Entry, a supplier that looks foreign"
```

---

### Task 7: The foreign flag on the party API

**Files:**
- Modify: `api/serializers/classify.py` (`PartySerializer.Meta.fields`)
- Test: `api/tests/test_boe.py` (add)

**Interfaces:**
- Produces: `is_foreign` readable and writable on `/clients/{id}/parties/`.

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_boe.py`:

```python
def test_a_party_can_be_marked_foreign(api, client_record):
    from api.tests.test_bills import make_party

    party = make_party(api, client_record, name="Shenzhen Parts Ltd", gstin="")

    changed = api.patch(f"{base(client_record)}/parties/{party['id']}/", {"is_foreign": True}, format="json")

    assert changed.status_code == 200 and changed.json()["is_foreign"] is True
```

- [ ] **Step 2: Implement**

In `api/serializers/classify.py` `PartySerializer.Meta.fields`, add `"is_foreign",` after `"msme",`.

- [ ] **Step 3: Commit**

```bash
git add api/serializers/classify.py api/tests/test_boe.py
git commit -m "Parties: is_foreign is set on the party and returned by the API"
```

---

### Task 8: The Bill of Entry API

**Files:**
- Create: `api/serializers/boe.py`, `api/views/boe.py`
- Modify: `api/urls.py`
- Modify: `web/openapi.yaml`, `web/src/api/schema.d.ts` (regenerated)
- Test: `api/tests/test_boe.py` (add)

**Interfaces:**
- Consumes: `boe.post_boe`, `billing.remove_bill`, `billing.open_amount`.
- Produces: `POST/GET /clients/{id}/bills-of-entry/`, `GET /…/{id}/`, `DELETE /…/{id}/?release_payments=true`. Response fields: `id` (the BoE side-record id), `bill` (the bill id), `entry` (the voucher id), `port_code`, `boe_number`, `boe_date`, `icegate_ref_date`, `assessable_paise`, `bcd_paise`, `sws_paise`, `igst_paise`, `cess_paise`, `total_paise`, `settled_paise`, `open_paise`, `party_name`, `document`.

- [ ] **Step 1: Write the failing API tests**

Append to `api/tests/test_boe.py`:

```python
def boe_body(**over):
    body = {
        "port_code": "INBOM4", "boe_number": "2345678", "boe_date": "2025-06-10",
        "assessable_paise": 10_00_000, "bcd_paise": 1_00_000, "sws_paise": 10_000, "igst_paise": 2_05_800,
    }
    body.update(over)
    return body


def test_a_bill_of_entry_is_booked_over_the_api_and_listed_with_what_is_settled(api, client_record):
    url = f"{base(client_record)}/bills-of-entry/"

    created = api.post(url, boe_body(), format="json")
    listed = api.get(url)

    assert created.status_code == 201, created.content
    body = created.json()
    assert body["total_paise"] == 3_15_800 and body["settled_paise"] == 0 and body["open_paise"] == 3_15_800
    assert body["party_name"] == "Customs (INBOM4)"
    assert [row["boe_number"] for row in listed.json()["results"]] == ["2345678"]


def test_a_bad_figure_is_refused_in_words(api, client_record):
    response = api.post(f"{base(client_record)}/bills-of-entry/", boe_body(assessable_paise=0), format="json")

    assert response.status_code in (400, 422)
    assert "assessable" in response.content.decode().lower()


def test_a_bill_of_entry_is_removed_over_the_api(api, client_record):
    url = f"{base(client_record)}/bills-of-entry/"
    created = api.post(url, boe_body(), format="json").json()

    gone = api.delete(f"{url}{created['id']}/")

    assert gone.status_code == 204
    assert api.get(url).json()["results"] == []


def test_a_read_only_member_can_list_but_not_book(reader, client_record):
    url = f"{base(client_record)}/bills-of-entry/"

    assert reader.get(url).status_code == 200
    assert reader.post(url, boe_body(), format="json").status_code == 403
```

(`reader` is defined in `api/tests/conftest.py`, so it needs no import.)

- [ ] **Step 2: Write the serializers**

Create `api/serializers/boe.py`:

```python
"""A customs Bill of Entry: what is entered, and what has been paid against it."""

from __future__ import annotations

import datetime

from rest_framework import serializers

from api.fields import PaiseField
from core.identifiers import is_valid_gstin
from ledger.models import BillOfEntry


class BillOfEntrySerializer(serializers.ModelSerializer):
    bill = serializers.UUIDField(source="bill_id", read_only=True)
    entry = serializers.UUIDField(source="bill.entry_id", read_only=True)
    document = serializers.UUIDField(source="bill.document_id", read_only=True, allow_null=True)
    party_name = serializers.CharField(source="bill.party.canonical_name", read_only=True)
    total_paise = serializers.IntegerField(source="bill.total_paise", read_only=True)
    settled_paise = serializers.SerializerMethodField()
    open_paise = serializers.SerializerMethodField()

    class Meta:
        model = BillOfEntry
        fields = [
            "id", "bill", "entry", "document", "party_name", "port_code", "boe_number", "boe_date", "icegate_ref_date",
            "assessable_paise", "bcd_paise", "sws_paise", "igst_paise", "cess_paise", "total_paise", "settled_paise", "open_paise",
        ]
        read_only_fields = fields

    def get_settled_paise(self, record) -> int:
        return getattr(record.bill, "settled_paise", 0) or 0

    def get_open_paise(self, record) -> int:
        return record.bill.total_paise - (getattr(record.bill, "settled_paise", 0) or 0)


class BillOfEntryCreateSerializer(serializers.Serializer):
    port_code = serializers.CharField(max_length=10)
    boe_number = serializers.CharField(max_length=20)
    boe_date = serializers.DateField()
    icegate_ref_date = serializers.DateField(required=False, allow_null=True, default=None)
    assessable_paise = PaiseField(min_value=0, help_text="The value Customs assessed. It is the foreign invoice, not posted here.")
    bcd_paise = PaiseField(required=False, default=0, min_value=0, help_text="Basic customs duty.")
    sws_paise = PaiseField(required=False, default=0, min_value=0, help_text="Social welfare surcharge.")
    igst_paise = PaiseField(required=False, default=0, min_value=0)
    cess_paise = PaiseField(required=False, default=0, min_value=0)
    landed_cost_ledger = serializers.UUIDField(
        required=False, allow_null=True, default=None, help_text="Where the duty that becomes cost is posted. Default: Purchases."
    )
    own_gstin = serializers.CharField(required=False, allow_blank=True, default="")
    document = serializers.UUIDField(required=False, allow_null=True, default=None, help_text="The Bill of Entry file, if uploaded.")
    narration = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)

    def validate_own_gstin(self, value: str) -> str:
        value = (value or "").strip().upper()
        if value and not is_valid_gstin(value):
            raise serializers.ValidationError("Not a valid GSTIN.")
        return value

    def validate_boe_date(self, value: datetime.date) -> datetime.date:
        if value > datetime.date.today():
            raise serializers.ValidationError("A Bill of Entry cannot be dated in the future.")
        return value
```

- [ ] **Step 3: Write the view**

Create `api/views/boe.py`:

```python
"""Customs Bills of Entry: booked as a bill owed to Customs, settled by ordinary payments."""

from __future__ import annotations

from django.db.models import BigIntegerField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.boe import BillOfEntryCreateSerializer, BillOfEntrySerializer
from api.views.base import ClientScopedMixin
from classify.models import LedgerAccount
from documents.models import Document
from ledger import billing, boe, invoice_intake
from ledger.models import BillOfEntry


@extend_schema(tags=["bills-of-entry"])
class BillOfEntryViewSet(
    ClientScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Customs Bills of Entry. Each is a bill owed to Customs, so a bank payment settles it, whole or in pieces."""

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve", "DELETE": "journal.approve"}
    queryset = BillOfEntry.objects.all()
    serializer_class = BillOfEntrySerializer

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(firm_id=self.request.firm.pk)
            .select_related("bill__party")
            .annotate(
                settled=Coalesce(Sum("bill__allocations__amount_paise"), Value(0), output_field=BigIntegerField())
            )
        )

    def get_serializer_class(self):
        return BillOfEntryCreateSerializer if self.action == "create" else BillOfEntrySerializer

    @extend_schema(
        summary="Book a Bill of Entry",
        description=(
            "Posts the duties in one voucher: basic duty and the social welfare surcharge to the landed-cost ledger, IGST "
            "and cess to the input credit ledgers, the total owed to a Customs party for the port. Refused inside "
            "signed-off books, and when the same number at the same port is already booked (422 `billing_rule`)."
        ),
        request=BillOfEntryCreateSerializer,
        responses={201: BillOfEntrySerializer},
    )
    def create(self, request, *args, **kwargs):
        payload = BillOfEntryCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        ledger = None
        if data["landed_cost_ledger"] is not None:
            ledger = get_object_or_404(LedgerAccount, pk=data["landed_cost_ledger"], firm_id=request.firm.pk, client=self.client)
        document = None
        if data["document"] is not None:
            document = get_object_or_404(Document, pk=data["document"], firm_id=request.firm.pk, client=self.client)
        bill = boe.post_boe(
            self.client,
            port_code=data["port_code"],
            boe_number=data["boe_number"],
            boe_date=data["boe_date"],
            figures=boe.BoeFigures(
                assessable_paise=data["assessable_paise"], bcd_paise=data["bcd_paise"], sws_paise=data["sws_paise"],
                igst_paise=data["igst_paise"], cess_paise=data["cess_paise"],
            ),
            membership=request.membership,
            landed_cost_ledger=ledger,
            icegate_ref_date=data["icegate_ref_date"],
            own_gstin=data["own_gstin"],
            document=document,
            narration=data["narration"],
        )
        # A payment already on Customs' account for exactly this amount is its payment.
        invoice_intake.settle_payment(bill)
        record = self.get_queryset().get(bill=bill)
        return Response(BillOfEntrySerializer(record).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Remove a Bill of Entry and its voucher",
        parameters=[OpenApiParameter("release_payments", bool, description="Also undo payments settled against it.")],
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        record = self.get_object()
        release = request.query_params.get("release_payments", "").lower() in {"1", "true", "yes"}
        billing.remove_bill(record.bill, membership=request.membership, release_payments=release)
        return Response(status=status.HTTP_204_NO_CONTENT)
```

Confirm `bill__allocations__amount_paise` annotation name collides with nothing: the serializer reads `record.bill.settled_paise`, so change the serializer to read the annotation `settled` from the record instead. In `BillOfEntrySerializer` replace the two `get_*` methods with:

```python
    def get_settled_paise(self, record) -> int:
        return getattr(record, "settled", 0) or 0

    def get_open_paise(self, record) -> int:
        return record.bill.total_paise - self.get_settled_paise(record)
```

- [ ] **Step 4: Register the route**

In `api/urls.py` add `from api.views.boe import BillOfEntryViewSet` beside the other view imports and, next to `stock-entries`:

```python
per_client.register("bills-of-entry", BillOfEntryViewSet, basename="client-bills-of-entry")
```

- [ ] **Step 5: Regenerate the contract**

Run: `python manage.py spectacular --file web/openapi.yaml`
Run: `cd web && npm run gen:api`
Expected: both succeed; `git diff --stat web/` shows `openapi.yaml` and `schema.d.ts` changed only for `bills-of-entry`, `is_foreign`, and `IMPORT_DUTY`.

- [ ] **Step 6: Run what can run and commit**

Run: `python -X utf8 manage.py check`
Expected: no issues. API tests run in CI.

```bash
git add api/serializers/boe.py api/views/boe.py api/urls.py web/openapi.yaml web/src/api/schema.d.ts api/tests/test_boe.py
git commit -m "Bills of Entry API: book, list with settled and open, remove"
```

---

### Task 9: The screens

**Files:**
- Create: `web/src/features/purchases/BillOfEntryDialog.tsx`
- Modify: `web/src/features/purchases/PurchasesScreen.tsx` (a button that opens it)
- Modify: `web/src/features/purchases/model.ts` and `model.test.ts` (Bills of Entry are not rows of the purchases list)
- Modify: `web/src/lib/vouchers.ts` (label and side for `IMPORT_DUTY`)
- Modify: `web/src/features/masters/MastersScreen.tsx` (party checkbox)
- Test: `web/src/features/purchases/BillOfEntryDialog.component.test.tsx`, `web/src/lib/vouchers.test.ts`

**Interfaces:**
- Consumes: `GET/POST/DELETE /clients/{id}/bills-of-entry/` from Task 8.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/lib/vouchers.test.ts` (inside the existing imports, add `isPurchaseSide, KIND_LABEL`):

```ts
describe('Bill of Entry in the generic bill screens', () => {
  it('is labelled and sits on the payable side', () => {
    expect(KIND_LABEL.IMPORT_DUTY).toBe('Bill of Entry (customs duty)')
    expect(isPurchaseSide('IMPORT_DUTY' as never)).toBe(true)
  })
})
```

Create `web/src/features/purchases/BillOfEntryDialog.component.test.tsx` following the pattern of `PurchasesScreen.component.test.tsx` (copy its render helper and mocked `raw`): render `<BillOfEntryDialog clientId="c1" onClose={...} />`, fill number `2345678`, port `INBOM4`, date, assessable `10,00,000`, BCD `1,00,000`, IGST `2,05,800`; assert the preview line reads `Customs is owed ₹3,05,800.00` and that pressing **Book** posts `{ port_code: 'INBOM4', boe_number: '2345678', assessable_paise: 100000000, bcd_paise: 10000000, ... igst_paise: 20580000 }` to `/clients/c1/bills-of-entry/`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/lib/vouchers.test.ts src/features/purchases/BillOfEntryDialog.component.test.tsx`
Expected: FAIL (label undefined; module not found).

- [ ] **Step 3: Labels and side**

In `web/src/lib/vouchers.ts`:

```ts
export const KIND_LABEL: Record<string, string> = {
  ...Object.fromEntries(VOUCHER_KINDS.map((k) => [k.value, k.label])),
  // Not postable from the voucher form (it has its own dialog), but it appears in the bill lists.
  IMPORT_DUTY: 'Bill of Entry (customs duty)',
}

export function isPurchaseSide(kind: VoucherKind): boolean {
  return kind === 'PURCHASE' || kind === 'DEBIT_NOTE' || (kind as string) === 'IMPORT_DUTY'
}
```

and add `|| (kind as string) === 'IMPORT_DUTY'` is not needed in `partySide` (a Bill of Entry is a credit like a purchase): change its condition to `kind === 'PURCHASE' || kind === 'CREDIT_NOTE' || (kind as string) === 'IMPORT_DUTY'`.

- [ ] **Step 4: The dialog**

Create `web/src/features/purchases/BillOfEntryDialog.tsx`, modelled on `web/src/features/reports/StockEntries.tsx` (same imports: `raw`, `V1`, `useInvalidateClient`, `messageOf`, `toast`, `Dialog`, `Field`, `Input`, `DateInput`, `Button`, `parseRupees`, `formatPaise`). Behaviour:

- A list of the client's Bills of Entry from `GET ${V1}/clients/${clientId}/bills-of-entry/` showing number, port, date, `total`, and `settled / total` (use `<Money>` or `formatPaise`), with a **Remove** button that calls `DELETE …/{id}/` (ask first with the existing `Confirm` component).
- A form: BoE number, port code, date, ICEGATE date (optional), assessable value, basic duty, social welfare surcharge, IGST, cess. Amounts are rupee strings converted once with `parseRupees(v || '0') ?? 0`.
- A live preview computed on the client for display only: `total = bcd + sws + igst + cess`, shown as "Customs is owed ₹…", with "of which ₹… is added to the cost of the goods and ₹… is input credit". The server is the authority.
- **Book** posts the body from Step 1's test and, on success, toasts `Booked`, refetches the list and calls `invalidate()`.
- Errors show `messageOf(e)` inline in a `role="alert"` paragraph.

- [ ] **Step 5: Open it from Purchases**

In `web/src/features/purchases/PurchasesScreen.tsx` add state `const [boeOpen, setBoeOpen] = useState(false)`, a secondary `Button` "Bill of Entry" beside the existing upload control (shown only when `can('journal.approve')`, the same check the screen already uses for booking), and `{boeOpen && <BillOfEntryDialog clientId={clientId} onClose={() => setBoeOpen(false)} />}` at the end of the component.

A Bill of Entry must not appear as a row in this list: a click on it would open the purchase voucher page (`ExpensePage`), which is built for the four voucher kinds and cannot save one. They are listed and removed in the dialog instead. Add a failing test to `web/src/features/purchases/model.test.ts` first:

```ts
it('leaves Bills of Entry out of the purchases list', () => {
  const boe = { id: 'b1', kind: 'IMPORT_DUTY', party_name: 'Customs (INBOM4)', bill_date: '2025-06-10', reference: '2345678', total_paise: 1, open_paise: 1 }
  expect(buildItems([], [boe as never])).toEqual([])
})
```

then, in `web/src/features/purchases/model.ts`, as the first line of `buildItems`:

```ts
  bills = bills.filter((b) => b.kind !== 'IMPORT_DUTY')
```

(change the parameter from a `const`-like binding if the linter objects: name the parameter `allBills` and write `const bills = allBills.filter(...)`). The dialog is also where a Bill of Entry's file would be linked; this slice has no file upload, so a Bill of Entry entered here shows the existing "no invoice file behind it" open item. That is accepted and listed as deferred; say so to the user.

- [ ] **Step 6: The party checkbox**

In `web/src/features/masters/MastersScreen.tsx` `PartyForm`: add `const [foreign, setForeign] = useState(party?.is_foreign ?? false)`, include `is_foreign: foreign` in `body`, and add beside the MSME checkbox:

```tsx
<Checkbox label="Supplier outside India (imports)" checked={foreign} onChange={(e) => setForeign(e.target.checked)} />
```

- [ ] **Step 7: Run and commit**

Run: `cd web && npx vitest run src/lib/vouchers.test.ts src/features/purchases src/features/masters`
Expected: PASS.
Run: `cd web && npx tsc --noEmit && npx oxlint src`
Expected: no errors.

```bash
git add web/src/features/purchases/BillOfEntryDialog.tsx web/src/features/purchases/BillOfEntryDialog.component.test.tsx web/src/features/purchases/PurchasesScreen.tsx web/src/features/purchases/model.ts web/src/features/purchases/model.test.ts web/src/lib/vouchers.ts web/src/lib/vouchers.test.ts web/src/features/masters/MastersScreen.tsx
git commit -m "Screens: enter a Bill of Entry from Purchases, see what is settled; mark a supplier as foreign"
```

---

### Task 10: Close the loop

**Files:**
- Modify: `docs/superpowers/specs/2026-10-11-bill-of-entry-design.md` (match what was built)
- Modify: `C:\Users\count\.claude\projects\E--autoca\memory\todo-open-list.md`

- [ ] **Step 1: Update the spec to match the plan**

In the spec: change the default landed-cost ledger to the existing standard ledger "Purchases"; state that the key is port + number (financial year already in the uniqueness constraint) and the date is not part of it; replace the party-screen foreign hint with the `party_looks_foreign` open item; remove the "customs payment with no BoE" detector bullet and list it under "Deferred": an open item for a customs payment that no BoE explains, needing a way to recognise such payments by narration when no party is set. Also list under "Deferred": ITC timing from `icegate_ref_date` (it is stored and shown, but the reconciliation does not yet use it), attaching the Bill of Entry file and reading it (the dialog has no upload, so each Bill of Entry shows the "no invoice file" open item until then), and pairing a Bill of Entry with its supplier invoice by value (they are paired by date within 60 days only, because the assessed value is at Customs' exchange rate and may be CIF against the invoice's FOB). In the spec also note that an unpaid Customs balance at year end sits in Trade payables because the party ledger is a creditor; statutory dues is arguably the right head, and the case is rare since duty is paid at clearance.

- [ ] **Step 2: Full local verification**

Run: `python -X utf8 -m pytest ledger/tests/test_boe_plan.py ledger/tests/test_matching_boe.py ledger/tests/test_foreign_pure.py gst/tests/test_matching_impg.py gst/tests/test_matching.py -q`
Expected: PASS.
Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.
Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS.

State plainly in the report which tests are DB tests that have not run (`api/tests/test_boe.py`, `ledger/tests/test_boe_model.py`, the tenant-isolation gate) and that they run only in CI.

- [ ] **Step 3: Update the memory note and commit**

Append to `todo-open-list.md` a short block: Bill of Entry built locally (not pushed), what is deferred (PDF reader, unexplained-customs-payment open item, foreign currency), and that DB tests wait for a CI push the user must approve.

```bash
git add docs/superpowers/specs/2026-10-11-bill-of-entry-design.md
git commit -m "Spec: match the Bill of Entry design to what was built"
```
