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


def post_run(api, client, run_id, **body):
    """Queue the posting, let the worker do it, and read the run back: the way a person's click ends."""
    from core import jobqueue

    queued = api.post(url(client, run_id, "confirm-vouchers"), body, format="json")
    if queued.status_code == 202:
        assert jobqueue.run_once("test-poster") == "succeeded"
    return queued, api.get(url(client, run_id, "voucher-run")).json()


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
    queued, done = post_run(api, client_record, run["id"])
    assert queued.status_code == 202 and queued.json()["posting"] is True
    assert done["status"] == "CONFIRMED" and done["result"]["posted"] == 1
    again = api.post(url(client_record, run["id"], "confirm-vouchers"))
    assert again.status_code == 200 and again.json()["result"]["posted"] == 1
    with firm_context(firm.pk):
        assert JournalEntry.objects.filter(client=client_record).count() == 1
        assert Bill.objects.filter(client=client_record).count() == 1
    undone = api.post(url(client_record, run["id"], "undo"))
    assert undone.status_code == 200 and undone.json()["status"] == "DISCARDED"
    with firm_context(firm.pk):
        assert JournalEntry.objects.filter(client=client_record).count() == 0


def test_a_period_that_already_has_entries_is_a_warning_the_accountant_decides(api, firm, client_record, chart):
    run = upload(api, client_record).json()
    post_run(api, client_record, run["id"])
    again = upload(api, client_record, [sale("g2", "2")])
    assert again.status_code == 201 and again.json()["counts"]["existing_entries"] == 1
    refused = api.post(url(client_record, again.json()["id"], "confirm-vouchers"), {}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "tally_overlap"
    _queued, done = post_run(api, client_record, again.json()["id"], allow_overlap=True)
    assert done["status"] == "CONFIRMED" and done["result"]["posted"] == 1


def test_a_queued_import_keeps_its_file_and_can_be_read_again_or_discarded(api, firm, client_record, chart):
    run = upload(api, client_record).json()
    assert run["file_name"] == "vouchers.xml" and run["document"]
    listed = api.get(url(client_record, "voucher-runs")).json()
    assert [r["id"] for r in listed] == [run["id"]] and "rows" not in listed[0]
    assert api.get(f"{V1}/documents/{run['document']}/download/").status_code == 200
    fresh = api.post(url(client_record, run["id"], "refresh-vouchers"), {}, format="json")
    assert fresh.status_code == 200 and fresh.json()["counts"]["vouchers"] == 1
    discarded = api.post(url(client_record, fresh.json()["id"], "discard"))
    assert discarded.status_code == 200 and discarded.json()["status"] == "DISCARDED"
    assert api.post(url(client_record, fresh.json()["id"], "confirm-vouchers"), {}, format="json").status_code == 409


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
    # The other firm is made before any request, because a request fixes the tenant for the rest of the test's transaction.
    other_firm = create_firm("Other Firm")
    other_client = create_client(other_firm, "Other Client", datetime.date(2025, 4, 1))
    from api.tests.conftest import member
    from core.models import Role

    outsider = sign_in(member(other_firm, Role.SENIOR_CA, "outsider@example.test").user)
    run = upload(api, client_record).json()
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


# ---------------------------------------------------------------------------
# Setting a client up from the files, and importing bank reports
# ---------------------------------------------------------------------------


def _files(*pairs):
    return [SimpleUploadedFile(name, data, content_type="text/xml") for name, data in pairs]


def test_discover_proposes_the_ledgers_and_writes_nothing(api, firm, client_record):
    from classify.models import LedgerAccount

    response = api.post(url(client_record, "discover"), {"files": _files(("vouchers.xml", vouchers_xml([sale()])))}, format="multipart")
    assert response.status_code == 200
    body = response.json()
    assert body["vouchers"] == 1 and body["voucher_files"] == 1
    groups = {p["name"]: p["group"] for p in body["ledgers"]}
    assert groups["Acme Traders"] == "DEBTOR" and groups["Sales"] == "SALES"
    with firm_context(firm.pk):
        assert not LedgerAccount.objects.filter(client=client_record, name="Acme Traders").exists()


def test_setup_creates_what_was_confirmed_then_the_vouchers_import(api, firm, client_record):
    from classify.models import LedgerAccount

    found = api.post(url(client_record, "discover"), {"files": _files(("vouchers.xml", vouchers_xml([sale()])))}, format="multipart").json()
    done = api.post(url(client_record, "setup"), {"ledgers": [{"name": p["name"], "group": p["group"]} for p in found["ledgers"]], "accounts": []}, format="json")
    assert done.status_code == 200 and done.json()["ledgers"] == 4
    with firm_context(firm.pk):
        assert LedgerAccount.objects.get(client=client_record, name="Output CGST").group == "DUTIES_AND_TAXES"
    run = upload(api, client_record).json()
    assert run["counts"]["will_post"] == 1
    assert post_run(api, client_record, run["id"])[1]["result"]["bills"] == 1


def test_setup_refuses_a_group_that_is_not_ours(api, client_record):
    response = api.post(url(client_record, "setup"), {"ledgers": [{"name": "Rent", "group": "NOT_A_GROUP"}]}, format="json")
    assert response.status_code == 400


def test_discover_refuses_a_file_that_is_not_xml(api, client_record):
    response = api.post(url(client_record, "discover"), {"files": _files(("masters.csv", b"a,b"))}, format="multipart")
    assert response.status_code == 400


def test_bank_reports_preview_and_confirm(api, firm, client_record):
    from banking.models import BankAccount
    from ledger.tests.tally_voucher_xml import bank_report_xml, report_row

    api.post(url(client_record, "setup"), {
        "ledgers": [{"name": "Cash", "group": "CASH"}],
        "accounts": [{"ledger": "SBI SB A/C 62139251173", "kind": "BANK", "bank_code": "SBI", "account_number": "62139251173"}],
    }, format="json")
    with firm_context(firm.pk):
        account = BankAccount.objects.get(client=client_record)
    data = bank_report_xml([report_row("4-Apr-25", "Cash", "Rcpt", debit=100.0, narration="CASH DEP", number="1")])
    response = api.post(
        url(client_record, "bank-report"),
        {"files": _files(("sbi.xml", data)), "accounts": [str(account.pk)]},
        format="multipart",
    )
    assert response.status_code == 201
    run = response.json()
    assert run["counts"]["bank_rows"] == 1
    done = post_run(api, client_record, run["id"])[1]
    assert done["result"]["posted"] == 1 and done["result"]["bank_rows"] == 1


def test_a_bank_report_needs_an_account_for_each_file(api, client_record):
    from ledger.tests.tally_voucher_xml import bank_report_xml, report_row

    data = bank_report_xml([report_row("4-Apr-25", "Cash", "Rcpt", debit=1.0)])
    response = api.post(url(client_record, "bank-report"), {"files": _files(("a.xml", data))}, format="multipart")
    assert response.status_code == 400


def test_discover_skips_a_file_it_cannot_use_and_says_why_instead_of_failing_the_rest(api, firm, client_record):
    not_vouchers = b"<ENVELOPE><SOMETHINGELSE>a GST report, not vouchers</SOMETHINGELSE></ENVELOPE>"
    files = _files(("vouchers.xml", vouchers_xml([sale()])), ("report.xml", not_vouchers))
    response = api.post(url(client_record, "discover"), {"files": files}, format="multipart")
    assert response.status_code == 200
    body = response.json()
    assert body["vouchers"] == 1 and body["voucher_files"] == 1
    assert [f["file"] for f in body["ignored"]] == ["report.xml"] and body["ignored"][0]["reason"]


def test_discover_still_refuses_when_no_file_is_usable(api, firm, client_record):
    response = api.post(url(client_record, "discover"), {"files": _files(("report.xml", b"<ENVELOPE><X/></ENVELOPE>"))}, format="multipart")
    assert response.status_code in (400, 422)
