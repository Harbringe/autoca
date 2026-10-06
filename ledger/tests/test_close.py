"""The close page: controls, open items, and sign-off waiting on what blocks it until it is fixed or explained."""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import PermissionDenied

from core.db.session import firm_context
from documents.models import Document, DocumentKind
from ledger import books, close
from ledger.models import InvoiceReading
from ledger.tests.test_signoff import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    membership_for,
    posted,
    senior,
    staff,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def an_unbooked_invoice(client):
    document = Document.objects.create(
        firm_id=client.firm_id, client=client, kind=DocumentKind.PURCHASE_INVOICE, sha256=uuid.uuid4().hex * 2, original_filename="inv.pdf"
    )
    return InvoiceReading.objects.create(firm_id=client.firm_id, client=client, document=document, kind="PURCHASE")


def blocking(report):
    return [i for i in report.items if i.blocking]


def test_the_report_names_each_control_and_passes_those_that_hold(client, posted):
    with firm_context(client.firm_id):
        report = close.close_report(client)

    named = {c.name: c.ok for c in report.checks}
    assert named["rows_posted"] is True and named["assistant_entries_checked"] is True and named["suspense_clear"] is True
    assert report.through is not None


def test_an_unbooked_invoice_is_a_blocking_item_until_it_is_explained(client, posted):
    with firm_context(client.firm_id):
        an_unbooked_invoice(client)

        before = close.close_report(client)

        (item,) = blocking(before)
        assert item.item.kind == "invoice_unbooked" and not item.explained
        assert before.unexplained_blocking == 1 and before.ready is False


def test_sign_off_waits_on_a_blocking_item_and_goes_ahead_once_it_is_explained(client, posted, staff, senior):
    with firm_context(client.firm_id):
        an_unbooked_invoice(client)
        books.request_review(client, staff)

        with pytest.raises(close.UnexplainedItemsError) as refused:
            books.sign_off(client, senior)
        assert refused.value.count == 1

        (item,) = blocking(close.close_report(client))
        close.explain(client, item.key, "Supplier is sending a corrected copy", membership=senior)

        after = close.close_report(client)
        assert after.unexplained_blocking == 0
        # The item stays listed, with the reason.
        (still,) = blocking(after)
        assert still.explained and still.note == "Supplier is sending a corrected copy"
        books.sign_off(client, senior)


def test_withdrawing_the_reason_makes_it_block_again(client, posted, senior):
    with firm_context(client.firm_id):
        an_unbooked_invoice(client)
        (item,) = blocking(close.close_report(client))
        close.explain(client, item.key, "Waiting for the supplier", membership=senior)

        close.withdraw(client, item.key, membership=senior)

        assert close.close_report(client).unexplained_blocking == 1


def test_only_someone_who_may_sign_off_can_explain(client, posted, staff):
    with firm_context(client.firm_id):
        an_unbooked_invoice(client)
        (item,) = blocking(close.close_report(client))

        with pytest.raises(PermissionDenied):
            close.explain(client, item.key, "Waiting for the supplier", membership=staff)


def test_an_explanation_needs_a_reason_and_a_real_item(client, posted, senior):
    with firm_context(client.firm_id):
        an_unbooked_invoice(client)
        (item,) = blocking(close.close_report(client))

        with pytest.raises(close.CloseError):
            close.explain(client, item.key, "ok", membership=senior)
        with pytest.raises(close.CloseError):
            close.explain(client, "invoice_unbooked|invoice|not-an-item", "Waiting for the supplier", membership=senior)


def test_an_explanation_lapses_with_the_item(client, posted, senior):
    with firm_context(client.firm_id):
        reading = an_unbooked_invoice(client)
        (item,) = blocking(close.close_report(client))
        close.explain(client, item.key, "Waiting for the supplier", membership=senior)

        reading.status = "DISCARDED"
        reading.save()

        assert blocking(close.close_report(client)) == []
