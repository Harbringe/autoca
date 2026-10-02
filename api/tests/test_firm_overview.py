"""``GET /api/v1/firm/overview/``: every visible client's stage in a fixed number of queries (B1)."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.tests.conftest import member, sign_in
from banking.models import Statement
from classify.models import TransactionClassification
from core.db.session import firm_context
from core.models import Client, ClientAssignment, Role
from core.provisioning import create_client, create_firm
from ledger.models import BooksAction, BooksEvent, EntryMarker, JournalEntry
from ledger.overview import _missing_months

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
URL = f"{V1}/firm/overview/"


def _row(http, client):
    rows = http.get(URL).json()["clients"]
    return next(r for r in rows if r["id"] == str(client.pk))


def test_a_client_with_no_statement_needs_one(api, client_record):
    body = api.get(URL).json()
    row = body["clients"][0]
    assert row["id"] == str(client_record.pk)
    assert row["stage"] == "no_statements"
    assert row["next_step"] == {"code": "upload", "label": "Upload a bank statement", "count": 0}
    assert row["last_statement_end"] is None and row["months_missing"] == []
    assert body["by_stage"]["no_statements"] == 1
    assert body["totals"]["clients"] == 1


def test_it_agrees_with_the_per_client_endpoints(api, client_record, statement):
    summary = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()
    row = _row(api, client_record)

    assert summary["unresolved"] > 0
    assert row["stage"] == "needs_ledger"
    assert row["unresolved"] == summary["unresolved"]
    assert row["pending_approval"] == summary["pending_approval"]
    assert row["assistant_waiting"] == summary["assistant_waiting"]
    assert row["next_step"]["code"] == "place" and row["next_step"]["count"] == summary["unresolved"]
    assert str(summary["unresolved"]) in row["next_step"]["label"]
    with firm_context(client_record.firm_id):
        assert row["last_statement_end"] == str(max(Statement.objects.values_list("period_end", flat=True)))


def test_stage_follows_the_books_once_every_row_is_dealt_with(api, client_record, statement, firm):
    """Nothing waiting: in review while a request is open, then send for review, then signed off."""
    with firm_context(firm.pk):
        TransactionClassification.objects.all().delete()
        end = Statement.objects.get().period_end
        BooksEvent.objects.create(firm=firm, client=client_record, action=BooksAction.REQUESTED)

    row = _row(api, client_record)
    assert (row["stage"], row["review_pending"], row["next_step"]["code"]) == ("in_review", True, "sign_off")
    assert row["next_step"]["label"] == "Sent for review"

    with firm_context(firm.pk):
        BooksEvent.objects.create(firm=firm, client=client_record, action=BooksAction.RETURNED, note="fix")
    row = _row(api, client_record)
    assert (row["stage"], row["review_pending"], row["next_step"]["code"]) == ("ready_for_review", False, "send_for_review")
    assert row["next_step"]["label"] == "Send for review"

    early = end - datetime.timedelta(days=3)
    with firm_context(firm.pk):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=early)
    row = _row(api, client_record)
    assert row["stage"] == "ready_for_review"
    assert row["next_step"]["label"] == f"Send for review (after {early:%d-%m-%Y})"

    with firm_context(firm.pk):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=end)
    row = _row(api, client_record)
    assert row["stage"] == "signed_off" and row["signed_off_through"] == str(end)
    assert row["next_step"]["code"] == "none"


def test_assistant_entries_count_only_after_the_last_sign_off(api, client_record, statement, firm):
    from classify.treatment import ReviewBand

    posted = api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    assert posted.status_code == 201
    with firm_context(firm.pk):
        entries = JournalEntry.objects.filter(client=client_record)
        total = entries.count()
        assert total > 0
        entries.filter(pk__in=list(entries.values_list("pk", flat=True)[:2])).update(marker=EntryMarker.AI_POSTED)
        marked = entries.exclude(marker=EntryMarker.NONE).count()
    row = _row(api, client_record)
    assert row["ai_unchecked"] == marked
    assert api.get(f"{V1}/clients/{client_record.pk}/books/").json()["ai_posted"] == marked

    with firm_context(firm.pk):
        latest = JournalEntry.objects.filter(client=client_record).order_by("-entry_date").first().entry_date
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=latest)
    assert _row(api, client_record)["ai_unchecked"] == 0


def test_months_missing_is_read_per_bank_account():
    d = datetime.date
    assert _missing_months({}) == []
    assert _missing_months({"a": [(d(2025, 4, 1), d(2025, 4, 30)), (d(2025, 6, 1), d(2025, 6, 30))]}) == ["2025-05"]
    # a statement spanning a month boundary covers both months; one account's run does not flag another's
    assert _missing_months(
        {
            "a": [(d(2025, 4, 15), d(2025, 5, 14)), (d(2025, 6, 1), d(2025, 6, 30))],
            "b": [(d(2025, 8, 1), d(2025, 8, 31))],
        }
    ) == []
    assert _missing_months(
        {"a": [(d(2025, 12, 1), d(2025, 12, 31)), (d(2026, 2, 1), d(2026, 2, 28))]}
    ) == ["2026-01"]


def test_one_unbroken_statement_run_has_no_missing_month(api, client_record, statement, firm):
    with firm_context(firm.pk):
        Statement.objects.filter(pk=statement.pk).update(
            period_start=datetime.date(2025, 4, 1), period_end=datetime.date(2025, 6, 30)
        )
    row = _row(api, client_record)
    assert row["months_missing"] == [] and row["last_statement_end"] == "2025-06-30"


def test_staff_see_only_their_clients_and_no_other_firm_appears(firm, client_record, staff, senior, api):
    mine = client_record
    theirs = create_client(firm, "Not Assigned", datetime.date(2025, 4, 1))
    with firm_context(firm.pk):
        staff.scope_all_clients = False
        staff.save(update_fields=["scope_all_clients"])
        ClientAssignment.objects.create(firm=firm, client=mine, membership=staff)

    other_firm = create_firm("Somebody Else")
    outsider_client = create_client(other_firm, "Other Firm Client", datetime.date(2025, 4, 1))
    outsider = member(other_firm, Role.FIRM_ADMIN, "ov-out@example.test")
    admin = member(firm, Role.FIRM_ADMIN, "ov-admin@example.test")

    staff_body = sign_in(staff.user).get(URL).json()
    assert [r["id"] for r in staff_body["clients"]] == [str(mine.pk)]
    assert staff_body["totals"]["clients"] == 1 and sum(staff_body["by_stage"].values()) == 1

    ids = {r["id"] for r in sign_in(admin.user).get(URL).json()["clients"]}
    assert ids == {str(mine.pk), str(theirs.pk)}
    assert str(outsider_client.pk) not in ids

    assert [r["id"] for r in sign_in(outsider.user).get(URL).json()["clients"]] == [str(outsider_client.pk)]


def test_the_number_of_queries_does_not_grow_with_the_number_of_clients(api, firm, client_record, statement):
    api.get(URL)  # warm any per-process caches
    with CaptureQueriesContext(connection) as few:
        api.get(URL)
    for n in range(6):
        create_client(firm, f"More Client {n}", datetime.date(2025, 4, 1))
    with CaptureQueriesContext(connection) as many:
        assert len(api.get(URL).json()["clients"]) == 7
    assert len(many) == len(few)


def test_a_reader_may_look_and_a_signed_out_caller_may_not(reader, client_record):
    assert sign_in(reader.user).get(URL).status_code == 200
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code in {401, 403}


def test_the_schema_describes_it():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    operation = schema["paths"]["/api/v1/firm/overview/"]["get"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/FirmOverview")
    shape = schema["components"]["schemas"]["OverviewClient"]["properties"]
    assert {"stage", "next_step", "unresolved", "pending_approval", "assistant_waiting", "ai_unchecked",
            "review_pending", "signed_off_through", "last_statement_end", "months_missing"} <= set(shape)
