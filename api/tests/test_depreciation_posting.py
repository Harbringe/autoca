"""A year's depreciation is booked as one journal entry, once, and noticed if the register changes after."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_assets_api import machine_purchase, register  # noqa: F401  (fixture and helper)
from api.tests.test_bills import base
from core.db.session import firm_context
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def status(api, client_record, fy=2025):
    return api.get(f"{base(client_record)}/assets/depreciation/", {"fy": fy}).json()


def book(api, client_record, fy=2025):
    return api.post(f"{base(client_record)}/assets/depreciation/", {"fy": fy}, format="json")


def lines_of(entry_id):
    entry = JournalEntry.objects.get(pk=entry_id)
    return sorted((line.ledger_account.name, line.direction, line.amount_paise) for line in entry.lines.select_related("ledger_account"))


def test_booking_posts_one_balanced_entry_dated_31_march(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    register(api, client_record, machinery, bill)

    response = book(api, client_record)

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["posted_paise"] == 1_00_000_00 and body["stale"] is False
    with firm_context(client_record.firm_id):
        entry = JournalEntry.objects.get(pk=body["entry"])
        assert entry.entry_date == datetime.date(2026, 3, 31) and entry.voucher_type == "Journal"
        assert lines_of(entry.pk) == [("Depreciation", "DR", 1_00_000_00), ("Machinery", "CR", 1_00_000_00)]
        assert sum(line.signed_paise for line in entry.lines.all()) == 0


def test_a_year_is_booked_once(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    register(api, client_record, machinery, bill)
    book(api, client_record)

    again = book(api, client_record)

    assert again.status_code == 422 and "already booked" in again.json()["detail"]


def test_booking_with_nothing_to_depreciate_says_so(api, client_record):
    response = book(api, client_record)

    assert response.status_code == 422 and "No asset has depreciation" in response.json()["detail"]


def test_a_change_to_the_register_after_booking_is_flagged_and_can_be_redone(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    made = register(api, client_record, machinery, bill).json()
    book(api, client_record)

    api.post(f"{base(client_record)}/assets/{made['id']}/dispose/", {"disposed_on": "2025-09-30", "proceeds_paise": 1}, format="json")

    assert status(api, client_record)["stale"] is True
    removed = api.post(f"{base(client_record)}/assets/depreciation/remove/", {"fy": 2025}, format="json")
    assert removed.status_code == 200 and removed.json()["posted_paise"] is None
    assert book(api, client_record).json()["stale"] is False


def test_sealed_books_refuse_depreciation_dated_inside_them(api, client_record, machine_purchase):
    machinery, bill = machine_purchase
    register(api, client_record, machinery, bill)
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2026, 3, 31))

    refused = book(api, client_record)

    assert refused.status_code == 422 and "sealed through" in refused.json()["detail"]


def test_a_read_only_member_may_look_but_not_book(api, client_record, machine_purchase, reader):
    from api.tests.conftest import sign_in

    machinery, bill = machine_purchase
    register(api, client_record, machinery, bill)
    viewer = sign_in(reader.user)

    assert viewer.get(f"{base(client_record)}/assets/depreciation/", {"fy": 2025}).status_code == 200
    assert book(viewer, client_record).status_code == 403
