"""The purchase register can be the books' own bills, matched against GSTR-2B."""

from __future__ import annotations

import pytest

from api.tests.test_bills import make_ledger, make_party, post_bill, voucher
from api.tests.test_gst_api import ACME, ME, PORTAL, _file, _g, _start

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

OTHER_ME = _g("29AAAPL1234C1Z")


def book(api, client_record, party, purchases, reference, on, taxable, tax, own=ME, **extra):
    body = voucher(
        party, purchases, reference=reference, bill_date=on, own_gstin=own, cgst_paise=tax, sgst_paise=tax,
        heads=[{"ledger": purchases["id"], "amount_paise": taxable}], **extra,
    )
    response = post_bill(api, client_record, body)
    assert response.status_code == 201, response.content
    return response.json()


@pytest.fixture
def books(api, client_record):
    party = make_party(api, client_record, "Acme Supplies", gstin=ACME)
    purchases = make_ledger(api, client_record)
    book(api, client_record, party, purchases, "INV-1", "2026-08-12", 10_000_00, 900_00)
    book(api, client_record, party, purchases, "INV-3", "2026-08-25", 2_000_00, 180_00)
    book(api, client_record, party, purchases, "INV-0", "2026-07-30", 1_000_00, 90_00)  # another month
    return party, purchases


def test_the_register_is_the_months_bills_and_matches_against_2b(api, client_record, books):
    base, run = _start(api, client_record)

    loaded = api.post(f"{base}/runs/{run}/register-from-books/")

    assert loaded.status_code == 200, loaded.content
    body = loaded.json()
    assert body["rows"] == 2 and body["unassigned"] == 0
    assert body["run"]["has_register"] is True and body["run"]["register_from_books"] is True

    assert api.post(f"{base}/runs/{run}/portal/", _file("2b.json", PORTAL), format="multipart").status_code == 200
    reconciled = api.post(f"{base}/runs/{run}/reconcile/").json()
    assert reconciled["summary"]["eligible_paise"] == 1800_00
    assert [g["kind"] for g in reconciled["groups"]] == ["missing_in_2b", "matched"]


def test_an_uploaded_register_takes_over_again(api, client_record, books):
    base, run = _start(api, client_record)
    api.post(f"{base}/runs/{run}/register-from-books/")
    register = f"GSTIN,Invoice No,Date,Taxable Value,CGST,SGST\n{ACME},INV-9,12-08-2026,100,9,9\n".encode()

    api.post(f"{base}/runs/{run}/register/", _file("r.csv", register), format="multipart")

    shown = api.get(f"{base}/runs/{run}/").json()
    assert shown["register_from_books"] is False and shown["has_register"] is True


def test_with_two_registrations_a_bill_with_no_gstin_is_counted_not_guessed(api, client_record, books):
    party, purchases = books
    book(api, client_record, party, purchases, "INV-4", "2026-08-28", 500_00, 45_00, own="")
    base, run = _start(api, client_record)
    api.post(f"{base}/registrations/", {"gstin": OTHER_ME}, format="json")

    body = api.post(f"{base}/runs/{run}/register-from-books/").json()

    assert body["rows"] == 2 and body["unassigned"] == 1


def test_a_signed_off_run_cannot_have_its_register_replaced(api, client_record, books):
    base, run = _start(api, client_record)
    api.post(f"{base}/runs/{run}/register-from-books/")
    api.post(f"{base}/runs/{run}/portal/", _file("2b.json", PORTAL), format="multipart")
    api.post(f"{base}/runs/{run}/reconcile/")
    api.post(f"{base}/runs/{run}/sign-off/")

    again = api.post(f"{base}/runs/{run}/register-from-books/")

    assert again.status_code == 409 and again.json()["code"] == "gst_rule"

