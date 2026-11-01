"""The tables behind a firm's own voucher series, number formats, voucher classes and the master audit trail."""

from __future__ import annotations

import datetime

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.provisioning import create_client
from ledger.models import (
    CustomVoucherType,
    JournalEntry,
    MasterChange,
    NumberingFormat,
    VoucherClass,
    VoucherSequence,
    VoucherType,
)
from ledger.tests.support import make_ledger
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    START,
    client,
    firm,
    member,
    senior,
)

pytestmark = pytest.mark.django_db


def entry(firm, client, *, type_name: str, number: int) -> JournalEntry:
    return JournalEntry.objects.create(
        firm_id=firm.pk,
        client=client,
        entry_no=number,
        financial_year=2025,
        entry_date=datetime.date(2025, 4, 1),
        voucher_type=VoucherType.SALES,
        type_name=type_name,
        approved_at=timezone.now(),
    )


def test_two_series_with_the_same_parent_can_both_hold_number_one(firm, client):
    with firm_context(firm.pk):
        entry(firm, client, type_name="", number=1)
        entry(firm, client, type_name="GST SALE", number=1)
        with pytest.raises(IntegrityError), transaction.atomic():
            entry(firm, client, type_name="GST SALE", number=1)


def test_each_series_has_its_own_counter_row(firm, client):
    with firm_context(firm.pk):
        for name in ("", "GST SALE"):
            VoucherSequence.objects.create(firm_id=firm.pk, client=client, financial_year=2025, voucher_type=VoucherType.SALES, type_name=name)
        with pytest.raises(IntegrityError), transaction.atomic():
            VoucherSequence.objects.create(
                firm_id=firm.pk, client=client, financial_year=2025, voucher_type=VoucherType.SALES, type_name="GST SALE"
            )


def test_a_numbering_format_is_unique_per_series(firm, client):
    with firm_context(firm.pk):
        NumberingFormat.objects.create(firm_id=firm.pk, client=client, voucher_type=VoucherType.SALES, type_name="", prefix="S/", padding=4)
        with pytest.raises(IntegrityError), transaction.atomic():
            NumberingFormat.objects.create(firm_id=firm.pk, client=client, voucher_type=VoucherType.SALES, type_name="", prefix="X/", padding=2)


def test_a_custom_voucher_type_name_is_unique_per_client(firm, client):
    with firm_context(firm.pk):
        CustomVoucherType.objects.create(firm_id=firm.pk, client=client, name="GST SALE", parent=VoucherType.SALES)
        with pytest.raises(IntegrityError), transaction.atomic():
            CustomVoucherType.objects.create(firm_id=firm.pk, client=client, name="GST SALE", parent=VoucherType.PURCHASE)


def test_a_class_cannot_name_another_clients_ledger(firm, client):
    with firm_context(firm.pk):
        other = create_client(firm, "Other Client", START)
        mine = make_ledger(client, "Sales", G.SALES)
        theirs = make_ledger(other, "Sales", G.SALES)
        VoucherClass.objects.create(firm_id=firm.pk, client=client, name="Retail", voucher_type=VoucherType.SALES, head_ledger=mine)
        connection.check_constraints()  # the same-client rule is deferred to commit; check it now
        with pytest.raises(IntegrityError), transaction.atomic():
            VoucherClass.objects.create(firm_id=firm.pk, client=client, name="Wrong", voucher_type=VoucherType.SALES, head_ledger=theirs)
            connection.check_constraints()


def test_a_master_change_row_cannot_be_updated_or_deleted(firm, client):
    with firm_context(firm.pk):
        row = MasterChange.objects.create(
            firm_id=firm.pk, client=client, kind="LEDGER", object_id=client.pk, action="EDITED", label="Rent", before={"name": "Rent"}, after={"name": "Rent A/c"}
        )
    with firm_context(firm.pk), pytest.raises(DatabaseError), transaction.atomic():
        MasterChange.objects.filter(pk=row.pk).update(label="rewritten")
    with firm_context(firm.pk), pytest.raises(DatabaseError), transaction.atomic():
        MasterChange.objects.filter(pk=row.pk).delete()
