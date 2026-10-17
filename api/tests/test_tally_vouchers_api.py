"""Importing a client's Tally vouchers, from the outside: the flow, the roles, the limits and the errors."""

from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from api.tests.conftest import sign_in
from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.models import Bill, JournalEntry
from ledger.tests.support import make_ledger
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def url(client, *tail):
    return f"{V1}/clients/{client.pk}/tally-imports/" + "".join(f"{t}/" for t in tail)


@pytest.fixture
def chart(firm, client_record):
    with firm_context(firm.pk):
        for name, group in [
            ("Acme Traders", G.DEBTOR), ("Sales", G.SALES), ("Output CGST", G.DUTIES_AND_TAXES),
            ("Output SGST", G.DUTIES_AND_TAXES), ("Cash", G.CASH),
        ]:
            make_ledger(client_record, name, group)


def sale(guid="g1", number="1", date="20250401"):
    return voucher(
        guid=guid, vtype="Sales", number=number, date=date, party="Acme Traders", gstin="27ABCDE1234F1Z5",
        lines=[line("Acme Traders", 1180.0, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )


def upload(api, client, vouchers=None, *, data=None, name="vouchers.xml", **extra):
    data = data if data is not None else vouchers_xml(vouchers if vouchers is not None else [sale()])
    body = {"file": SimpleUploadedFile(name, data, content_type="text/xml"), **extra}
    return api.post(url(client, "vouchers"), body, format="multipart")


def test_upload_returns_a_trimmed_preview_and_posts_nothing(api, firm, client_record, chart):
    response = upload(api, client_record)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PREVIEW" and body["kind"] == "VOUCHERS" and body["result"] is None
    assert body["counts"]["will_post"] == 1 and body["counts"]["will_make_bill"] == 1
    row = body["rows"][0]
    assert row["action"] == "post" and row["bill"] is True and row["total_paise"] == 118000
    assert set(row) == {"ordinal", "type", "number", "date", "party", "total_paise", "action", "bill", "reason", "note"}
    assert "27ABCDE1234F1Z5" not in response.content.decode()
    with firm_context(firm.pk):
        assert JournalEntry.objects.filter(client=client_record).count() == 0


def test_the_same_upload_is_the_same_preview(api, client_record, chart):
    first = upload(api, client_record)
    second = upload(api, client_record)
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]


def test_confirm_posts_and_is_idempotent_and_undo_takes_it_back(api, firm, client_record, chart):
    run = upload(api, client_record).json()
    done = api.post(url(client_record, run["id"], "confirm-vouchers"))
    assert done.status_code == 200
    assert done.json()["status"] == "CONFIRMED" and done.json()["result"]["posted"] == 1
    assert api.post(url(client_record, run["id"], "confirm-vouchers")).json()["result"]["posted"] == 1
    with firm_context(firm.pk):
        assert JournalEntry.objects.filter(client=client_record).count() == 1
        assert Bill.objects.filter(client=client_record).count() == 1
    undone = api.post(url(client_record, run["id"], "undo"))
    assert undone.status_code == 200 and undone.json()["status"] == "DISCARDED"
    with firm_context(firm.pk):
        assert JournalEntry.objects.filter(client=client_record).count() == 0


def test_a_period_that_already_has_entries_is_409_tally_rule(api, firm, client_record, chart):
    run = upload(api, client_record).json()
    api.post(url(client_record, run["id"], "confirm-vouchers"))
    again = upload(api, client_record, [sale("g2", "2")])
    assert again.status_code == 409 and again.json()["code"] == "tally_rule"


def test_a_file_with_a_doctype_is_422(api, client_record, chart):
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
    response = upload(api, client_record, data=bomb)
    assert response.status_code == 422 and response.json()["code"] == "tally_file_unreadable"


def test_a_file_over_the_limit_is_413(api, client_record, chart, settings):
    settings.MAX_TALLY_IMPORT_BYTES = 1000
    response = upload(api, client_record, data=b"<ENVELOPE>" + b" " * 1500 + b"</ENVELOPE>")
    assert response.status_code == 413 and response.json()["code"] == "tally_file_too_large"


def test_only_xml_is_accepted(api, client_record, chart):
    response = upload(api, client_record, name="vouchers.csv")
    assert response.status_code == 400


def test_staff_who_may_not_import_are_refused(staff_api, client_record, chart):
    assert upload(staff_api, client_record).status_code == 403


def test_anonymous_is_refused(client_record):
    from rest_framework.test import APIClient

    assert upload(APIClient(), client_record).status_code in (401, 403)


def test_another_firms_run_is_not_found(api, firm, client_record, chart):
    run = upload(api, client_record).json()
    other_firm = create_firm("Other Firm")
    other_client = create_client(other_firm, "Other Client", datetime.date(2025, 4, 1))
    from api.tests.conftest import member
    from core.models import Role

    outsider = sign_in(member(other_firm, Role.SENIOR_CA, "outsider@example.test").user)
    assert outsider.post(url(other_client, run["id"], "confirm-vouchers")).status_code == 404
    assert outsider.post(url(client_record, run["id"], "confirm-vouchers")).status_code == 404


def test_a_masters_run_cannot_be_confirmed_as_vouchers(api, client_record, chart):
    from ledger.tests.tally_xml import ledger, masters_xml

    body = {
        "file": SimpleUploadedFile("m.xml", masters_xml([ledger("Rent", "Indirect Expenses")]), content_type="text/xml"),
        "financial_year": 2025,
    }
    masters = api.post(url(client_record), body, format="multipart").json()
    assert api.post(url(client_record, masters["id"], "confirm-vouchers")).status_code == 404
