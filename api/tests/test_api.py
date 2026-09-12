"""The API, from the outside.

These go through the full stack -- URL routing, session auth, the MFA gate, the
tenant middleware, RLS, RBAC, the domain, and back out through a serializer.
That is the point: the guarantees this system makes are only worth anything if
they hold at the edge a client actually touches.
"""

from __future__ import annotations

import datetime
import json

import pytest
from rest_framework.test import APIClient

from api.tests.conftest import member, sign_in
from classify.engine import review_queue
from classify.models import LedgerAccount, LedgerGroup
from classify.treatment import ReviewBand
from core.models import Role
from core.provisioning import create_client, create_firm
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def ledger(client_record, name, group=LedgerGroup.INDIRECT_EXPENSE):
    return LedgerAccount.objects.get_or_create(
        firm_id=client_record.firm_id, client=client_record, name=name,
        defaults={"group": group},
    )[0]


# ---------------------------------------------------------------------------
# Getting in
# ---------------------------------------------------------------------------


def test_anonymous_requests_are_refused(client_record):
    response = APIClient().get(f"{V1}/clients/")

    assert response.status_code in (401, 403)


def test_a_session_without_a_second_factor_is_told_so_in_json(staff):
    """Not redirected to an HTML page. A fetch() cannot read a 302."""
    http = APIClient()
    http.force_login(staff.user)

    response = http.get(f"{V1}/clients/")

    assert response.status_code == 403
    assert response.json()["code"] in {"mfa_required", "mfa_enrolment_required"}
    assert response.json()["verify_at"].startswith("/auth/mfa/")


def test_me_reports_the_firm_and_the_permissions(api, senior):
    body = api.get(f"{V1}/me/").json()

    assert body["email"] == senior.user.email
    assert body["firm"]["name"] == "API Test Firm"
    assert body["role"] == Role.SENIOR_CA
    assert "journal.approve" in body["permissions"]


def test_a_staff_session_does_not_claim_it_can_approve(staff_api):
    assert "journal.approve" not in staff_api.get(f"{V1}/me/").json()["permissions"]


# ---------------------------------------------------------------------------
# Tenant isolation, at the edge
# ---------------------------------------------------------------------------


def test_one_firm_cannot_see_another_firms_clients(api, client_record):
    other_firm = create_firm("Somebody Else")
    create_client(other_firm, "Not Yours", datetime.date(2025, 4, 1))

    names = [row["name"] for row in api.get(f"{V1}/clients/").json()["results"]]

    assert names == ["Acme Traders"]


def test_another_firms_client_is_not_found_even_by_id(client_record):
    """A 404 rather than a 403: the id's existence is itself not ours to confirm."""
    other_firm = create_firm("Somebody Else")
    outsider = sign_in(member(other_firm, Role.SENIOR_CA, "them@example.test").user)

    assert outsider.get(f"{V1}/clients/{client_record.pk}/").status_code == 404


def test_a_read_only_member_cannot_create_a_client(reader, firm):
    response = sign_in(reader.user).post(
        f"{V1}/clients/", {"name": "New", "fy_start": "2025-04-01"}, format="json"
    )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


# ---------------------------------------------------------------------------
# Money on the wire
# ---------------------------------------------------------------------------


def test_amounts_are_sent_as_integer_paise_and_a_formatted_string(api, client_record, statement):
    """The two things a client needs, and neither derived from the other.

    A JSON number with a decimal point becomes a float in a browser, which is
    the rounding error the whole backend exists to avoid.
    """
    body = api.get(f"{V1}/clients/{client_record.pk}/statements/{statement.pk}/").json()

    assert body["opening_balance_paise"] == 1_24_189_43
    assert body["opening_balance_display"] == "₹1,24,189.43"
    assert isinstance(body["closing_balance_paise"], int)
    assert body["closing_balance_display"] == "₹6,03,490.57"


def test_transaction_rows_carry_both_forms_too(api, client_record, statement):
    rows = api.get(
        f"{V1}/clients/{client_record.pk}/statements/{statement.pk}/transactions/"
    ).json()["results"]

    first = rows[0]
    assert first["debit_paise"] == 250_00
    assert first["debit_display"] == "₹250.00"
    assert first["narration"] == "Sweep/VO000000087559330/19000014841287"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_uploading_a_statement_returns_202_with_a_job(api, client_record):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("axis.pdf", b"%PDF-1.4 axis", content_type="application/pdf")
    response = api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/", {"file": upload}, format="multipart"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "statement.ingest"
    assert body["status"] == "SUCCEEDED"
    assert body["result"]["rows_created"] == 54
    assert body["result"]["needs_opening_confirmation"] is True


def test_an_unreadable_file_fails_the_job_rather_than_the_request(api, client_record, settings):
    """The upload was well-formed. The file was the problem, and the job says which."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from integrations.registry import reset_adapter_cache

    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "pdf": "integrations.pdf.pdfplumber_text.PdfPlumberAdapter"}
    reset_adapter_cache()

    # Carries the PDF signature, so it gets past the boundary check and to the
    # extractor -- which is the failure this test is about. A file without the
    # signature is refused earlier, with a 400; see test_hardening.
    upload = SimpleUploadedFile(
        "notes.pdf", b"%PDF-1.7 followed by nothing a PDF parser can read", content_type="application/pdf"
    )
    response = api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/", {"file": upload}, format="multipart"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error_code"] == "unreadable_file"
    assert body["error"]


def test_a_job_can_be_fetched_afterwards(api, client_record):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("axis.pdf", b"%PDF-1.4 axis", content_type="application/pdf")
    job_id = api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/", {"file": upload}, format="multipart"
    ).json()["id"]

    assert api.get(f"{V1}/jobs/{job_id}/").json()["status"] == "SUCCEEDED"


def test_job_events_stream_as_server_sent_events(api, client_record):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("axis.pdf", b"%PDF-1.4 axis", content_type="application/pdf")
    job_id = api.post(
        f"{V1}/clients/{client_record.pk}/statements/upload/", {"file": upload}, format="multipart"
    ).json()["id"]

    response = api.get(f"{V1}/jobs/{job_id}/events/")
    body = b"".join(response.streaming_content).decode()

    assert response["Content-Type"] == "text/event-stream"
    assert body.startswith("data: ")
    assert json.loads(body.removeprefix("data: ").strip())["status"] == "SUCCEEDED"


# ---------------------------------------------------------------------------
# The review queue
# ---------------------------------------------------------------------------


def test_the_queue_is_sorted_by_confidence(api, client_record, statement):
    rows = api.get(f"{V1}/clients/{client_record.pk}/review-queue/").json()["results"]

    confidences = [row["confidence"] for row in rows]
    assert confidences == sorted(confidences, reverse=True)
    assert rows[0]["review_band"] == ReviewBand.HIGH


def test_the_summary_says_how_much_is_bulk_approvable(api, client_record, statement):
    body = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()

    assert body["total"] == 54
    assert body["high"] == 4  # the seeded interest rows
    assert body["bulk_approvable"] == 4
    assert body["unresolved"] == 50
    assert body["pending_approval"] == 4


def test_a_queue_row_carries_everything_needed_to_decide(api, client_record, statement):
    rows = api.get(
        f"{V1}/clients/{client_record.pk}/review-queue/", {"band": ReviewBand.JUDGEMENT}
    ).json()["results"]

    row = next(r for r in rows if r["counterparty"] == "NPCI BHIM")
    assert row["channel"] == "UPI"
    assert row["ledger"] is None
    assert row["transaction"]["narration"].startswith("UPI/P2A/")
    assert row["transaction"]["amount_display"].startswith("₹")


def test_placing_a_row_teaches_a_rule_and_places_its_siblings(api, client_record, statement):
    cashback = ledger(client_record, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    row = review_queue(client_record).filter(counterparty="NPCI BHIM").first()

    response = api.post(
        f"{V1}/classifications/{row.pk}/review/",
        {"ledger": str(cashback.pk), "rcm": False, "learn": True},
        format="json",
    )

    body = response.json()
    assert response.status_code == 200
    assert body["classification"]["ledger_name"] == "Bhim Cash Back"
    assert body["rule_learned"] is not None
    assert body["also_placed"] == 8


def test_a_read_only_member_cannot_place_a_row(reader, client_record, statement):
    target = ledger(client_record, "Office Expenses")
    row = review_queue(client_record).first()

    response = sign_in(reader.user).post(
        f"{V1}/classifications/{row.pk}/review/", {"ledger": str(target.pk)}, format="json"
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Approval: the line that matters
# ---------------------------------------------------------------------------


def test_staff_cannot_approve(staff_api, client_record, statement):
    response = staff_api.post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )

    assert response.status_code == 403
    assert JournalEntry.objects.count() == 0


def test_a_senior_ca_can_bulk_approve_a_band(api, client_record, statement):
    response = api.post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )

    assert response.status_code == 201
    entries = response.json()
    assert len(entries) == 4
    assert all(entry["voucher_type"] == "Receipt" for entry in entries)
    assert entries[0]["lines"][0]["amount_display"].startswith("₹")


def test_approving_takes_the_rows_out_of_the_queue(api, client_record, statement):
    before = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()["total"]
    api.post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )
    after = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()["total"]

    assert after == before - 4


def test_approving_a_row_that_is_not_pending_is_rejected(api, client_record, statement):
    unresolved = review_queue(client_record).filter(ledger__isnull=True).first()

    response = api.post(
        f"{V1}/clients/{client_record.pk}/approvals/",
        {"classifications": [str(unresolved.pk)]},
        format="json",
    )

    assert response.status_code == 400
    assert "not awaiting approval" in json.dumps(response.json())


def test_a_posted_entry_cannot_be_reached_by_any_write_verb(api, client_record, statement):
    """There is no update or delete route. The ledger is append-only."""
    api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    entry = JournalEntry.objects.first()

    assert api.put(f"{V1}/journal-entries/{entry.pk}/", {}, format="json").status_code == 405
    assert api.delete(f"{V1}/journal-entries/{entry.pk}/").status_code == 405


def test_a_correction_is_a_new_entry_and_the_original_survives(api, client_record, statement):
    api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    original = JournalEntry.objects.first()
    elsewhere = ledger(client_record, "Other Income", LedgerGroup.INDIRECT_INCOME)

    response = api.post(
        f"{V1}/journal-entries/{original.pk}/correct/",
        {"treatment": {"ledger": str(elsewhere.pk)}},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["supersedes"] == str(original.pk)
    assert JournalEntry.objects.filter(pk=original.pk).exists()
    assert api.get(f"{V1}/journal-entries/{original.pk}/").json()["is_superseded"] is True


# ---------------------------------------------------------------------------
# Reports and reconciliation
# ---------------------------------------------------------------------------


def test_the_trial_balance_balances_and_says_it_is_incomplete(api, client_record, statement):
    api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")

    body = api.get(
        f"{V1}/clients/{client_record.pk}/reports/trial-balance/", {"fy": 2025}
    ).json()

    assert body["balances"] is True
    assert body["total_debit_paise"] == body["total_credit_paise"]
    assert body["footer"]["is_complete"] is False
    assert "INCOMPLETE" in body["footer"]["caption"]


def test_reports_reject_a_financial_year_that_is_not_a_year(api, client_record, statement):
    response = api.get(
        f"{V1}/clients/{client_record.pk}/reports/trial-balance/", {"fy": "twenty-five"}
    )

    assert response.status_code == 400
    assert "starting year" in json.dumps(response.json())


def test_reconciliation_explains_a_break(api, client_record, statement):
    account = statement.bank_account

    body = api.get(
        f"{V1}/bank-accounts/{account.pk}/reconciliation/", {"as_of": "2026-06-03"}
    ).json()

    assert body["matches"] is False
    assert body["can_close"] is False
    assert body["statement_balance_display"] == "₹6,03,490.57"
    assert "not been approved" in body["explanation"]


def test_reconciling_a_date_no_statement_covers_is_a_404(api, client_record, statement):
    response = api.get(
        f"{V1}/bank-accounts/{statement.bank_account.pk}/reconciliation/",
        {"as_of": "2030-01-01"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "no_statement_for_date"


def test_the_tally_export_carries_only_approved_entries(api, client_record, statement):
    api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")

    body = api.get(f"{V1}/statements/{statement.pk}/tally-export/").json()

    assert body["voucher_count"] == 4
    assert body["unapproved"] == 50
    assert body["xml"].startswith("<?xml")


# ---------------------------------------------------------------------------
# Opening balance
# ---------------------------------------------------------------------------


def test_confirming_an_opening_balance(api, client_record, statement):
    account = statement.bank_account

    response = api.post(
        f"{V1}/clients/{client_record.pk}/bank-accounts/{account.pk}/opening-balance/",
        {"opening_balance_paise": 1_24_189_43, "opening_as_of": "2025-04-01"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["has_opening_balance"] is True
    assert response.json()["opening_balance_display"] == "₹1,24,189.43"


def test_the_account_detail_shows_the_number_but_the_list_does_not(api, client_record, statement):
    """Decrypting thirty account numbers to render a list is not a thing to do."""
    account = statement.bank_account
    base = f"{V1}/clients/{client_record.pk}/bank-accounts/"

    listed = api.get(base).json()["results"][0]
    detail = api.get(f"{base}{account.pk}/").json()

    assert "account_number" not in listed
    assert listed["account_last4"] == "4321"
    assert detail["account_number"] == "911010000004321"
