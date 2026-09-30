"""The work numbers the Work page shows: books sent for review, entries posted, books to send."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from classify.models import LedgerAccount, TransactionClassification
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import ClientAssignment
from ledger.approval import auto_post_client
from ledger.models import BooksAction, BooksEvent, EntryMarker, JournalEntry
from teams.tests.test_team import TEAM, V1, _lead_client, _on_team, admin, lead  # noqa: F401

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _work(http, member):
    return http.get(f"{TEAM}/members/{member.pk}/work/").json()


def _event(client, actor, action=BooksAction.REQUESTED):
    with firm_context(client.firm_id):
        return BooksEvent.objects.create(firm_id=client.firm_id, client=client, action=action, actor=actor.user)


def test_books_sent_for_review_counts_the_requests_each_person_made(client_record, lead):
    _lead_client(client_record, lead)
    other = _on_team(client_record.firm, lead, "clerk@example.test")
    _event(client_record, lead)
    _event(client_record, lead, BooksAction.RETURNED)  # a senior's answer is not a request
    _event(client_record, lead)
    _event(client_record, other)

    work = _work(sign_in(lead.user), lead)

    assert work["totals"]["books_sent_for_review"] == 2
    assert [c["books_sent_for_review"] for c in work["by_client"]] == [2]
    assert sum(day["count"] for day in work["by_day"]) == 2
    assert {"key": "books_sent_for_review", "label": "Books sent for review", "note": ""} in work["metrics"]
    listed = {m["email"]: m for m in sign_in(lead.user).get(f"{TEAM}/members/").json()["results"]}
    assert listed[lead.user.email]["work"]["books_sent_for_review"] == 2
    assert listed[other.user.email]["work"]["books_sent_for_review"] == 1


def test_books_sent_for_review_respects_the_period(client_record, lead):
    _lead_client(client_record, lead)
    _event(client_record, lead)

    old = sign_in(lead.user).get(f"{TEAM}/members/{lead.pk}/work/?from=2020-01-01&to=2020-01-31").json()

    assert old["totals"]["books_sent_for_review"] == 0


def test_entries_posted_counts_entries_with_the_persons_name_and_not_the_assistants(
    firm, client_record, statement, lead
):
    _lead_client(client_record, lead)
    with firm_context(firm.pk):
        TransactionClassification.objects.filter(
            transaction__bank_account__client=client_record, ledger__isnull=False
        ).update(method="LLM", confidence=0.95, review_band=ReviewBand.HIGH, open_question="")
        assistant_posted = auto_post_client(client_record)
    assert assistant_posted > 0

    approved = sign_in(lead.user).post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )
    assert approved.status_code == 201

    work = _work(sign_in(lead.user), lead)["totals"]
    with firm_context(firm.pk):
        by_person = JournalEntry.objects.filter(client=client_record, approved_by=lead.user).count()
        by_assistant = JournalEntry.objects.filter(client=client_record, marker=EntryMarker.AI_POSTED).count()
    assert by_assistant == assistant_posted
    assert work["entries_posted"] == by_person == work["entries_approved"] + work["entries_corrected"]

    note = next(m["note"] for m in _work(sign_in(lead.user), lead)["metrics"] if m["key"] == "entries_posted")
    assert "approvals and corrections" in note and "nobody's name" in note


def test_a_person_with_no_posted_entries_shows_zero_not_the_assistants_work(firm, client_record, statement, lead):
    _lead_client(client_record, lead)
    with firm_context(firm.pk):
        TransactionClassification.objects.filter(
            transaction__bank_account__client=client_record, ledger__isnull=False
        ).update(method="LLM", confidence=0.95, review_band=ReviewBand.HIGH, open_question="")
        assert auto_post_client(client_record) > 0

    assert _work(sign_in(lead.user), lead)["totals"]["entries_posted"] == 0


def test_books_to_send_is_true_only_when_everything_is_posted_and_nothing_is_waiting(
    firm, client_record, statement, lead, admin
):
    _lead_client(client_record, lead)
    http = sign_in(admin.user)

    def row():
        return next(c for c in http.get(f"{TEAM}/clients/").json()["results"] if c["id"] == str(client_record.pk))

    assert row()["books_to_send"] is False, "rows are still unposted"

    with firm_context(firm.pk):
        rows = TransactionClassification.objects.filter(transaction__bank_account__client=client_record)
        ledger = LedgerAccount.objects.filter(client=client_record, status="ACTIVE", group="INDIRECT_EXPENSE").first()
        rows.filter(ledger__isnull=True).update(
            ledger=ledger, method="LLM", confidence=0.95, review_band=ReviewBand.HIGH, open_question=""
        )
    for band in (ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT):
        sign_in(lead.user).post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": band}, format="json")

    assert row()["unresolved"] == 0 and row()["pending_approval"] == 0
    assert row()["books_to_send"] is True
    assert _work(sign_in(lead.user), lead)["open_work"][0]["books_to_send"] is True

    _event(client_record, lead)
    assert row()["books_to_send"] is False, "a request is already waiting for a senior"


def test_books_to_send_is_false_for_a_client_with_no_entries(client_record, admin, lead):
    _lead_client(client_record, lead)
    rows = sign_in(admin.user).get(f"{TEAM}/clients/").json()["results"]
    assert rows[0]["books_to_send"] is False
