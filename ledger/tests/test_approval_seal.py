"""A senior's approval says "this is good" and locks nothing; the seal, on the client's schedule, is the permanent lock."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied

from classify.treatment import Treatment
from core.db.session import firm_context
from core.models import Client
from ledger import books, editing
from ledger.models import BooksAction
from ledger.tests.test_signoff import (  # noqa: F401  (fixtures and helpers)
    client,
    entries,
    firm,
    ledger,
    membership_for,
    posted,
    senior,
    staff,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def on(period):
    return SimpleNamespace(close_period=period)


# ---------------------------------------------------------------------------
# The schedule: pure
# ---------------------------------------------------------------------------


def test_a_quarterly_client_seals_at_each_quarter_end():
    dates = books.seal_dates(on("QUARTERLY"), upto=datetime.date(2026, 10, 6), after=datetime.date(2025, 12, 31))

    assert dates == [datetime.date(2026, 3, 31), datetime.date(2026, 6, 30), datetime.date(2026, 9, 30)]


def test_a_half_yearly_client_seals_in_september_and_march():
    dates = books.seal_dates(on("HALF_YEARLY"), upto=datetime.date(2026, 10, 6), after=datetime.date(2025, 3, 31))

    assert dates == [datetime.date(2025, 9, 30), datetime.date(2026, 3, 31), datetime.date(2026, 9, 30)]


def test_a_yearly_client_seals_only_in_march():
    dates = books.seal_dates(on("YEARLY"), upto=datetime.date(2026, 10, 6), after=datetime.date(2024, 3, 31))

    assert dates == [datetime.date(2025, 3, 31), datetime.date(2026, 3, 31)]


def test_a_date_that_has_not_come_is_not_a_seal_date_yet():
    assert books.seal_dates(on("QUARTERLY"), upto=datetime.date(2026, 6, 29), after=datetime.date(2026, 3, 31)) == []


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def request_and_approve(client, staff, senior, **kwargs):
    books.request_review(client, staff)
    return books.approve(client, senior, **kwargs)


def test_nothing_can_be_approved_until_it_has_been_requested(client, senior, posted):
    with firm_context(client.firm_id), pytest.raises(books.NothingRequestedError):
        books.approve(client, senior)


def test_approving_records_the_date_and_locks_nothing(client, staff, senior, posted):
    with firm_context(client.firm_id):
        latest = entries(client).last().entry_date

        event = request_and_approve(client, staff, senior, note="Looks right")

        assert event.action == BooksAction.APPROVED
        current = books.status(client)
        assert current.approved_through == latest and current.approved_by == senior.user.email
        assert not current.review_pending and current.changed_since_approval == 0
        assert Client.objects.get(pk=client.pk).signed_off_through is None


def test_an_approved_entry_can_still_be_changed_and_the_change_is_reported(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        entry = entries(client).first()

        editing.revise_in_place(entry, Treatment(ledger=ledger(client, "Rent")), actor=staff.user, note="It is rent")

        assert books.status(client).changed_since_approval == 1


def test_only_someone_who_may_sign_off_can_approve(client, staff, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff)
        with pytest.raises(PermissionDenied):
            books.approve(client, staff)


def test_returning_the_books_withdraws_an_earlier_approval(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        books.request_review(client, staff)

        books.return_for_changes(client, senior, note="Check the rent")

        assert books.status(client).approved_through is None


def test_a_change_after_approval_can_be_approved_again_without_a_new_request(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        editing.revise_in_place(entries(client).first(), Treatment(ledger=ledger(client, "Rent")), actor=staff.user)
        assert books.status(client).changed_since_approval == 1

        books.approve(client, senior)

        assert books.status(client).changed_since_approval == 0


# ---------------------------------------------------------------------------
# The seal
# ---------------------------------------------------------------------------


def sealable(client):
    current = books.status(client)
    return books.seal_dates(client, upto=min(current.approved_through, datetime.date.today()), after=current.signed_off_through)


def test_the_seal_needs_an_approval(client, staff, senior, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff)

        with pytest.raises(books.NotApprovedError):
            books.sign_off(client, senior, strict=True)


def test_the_seal_only_goes_on_a_date_the_schedule_names(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        dates = sealable(client)
        assert dates, "the fixture statement should span at least one quarter end"
        not_a_quarter_end = dates[0] - datetime.timedelta(days=3)

        with pytest.raises(books.NotASealDateError) as refused:
            books.sign_off(client, senior, through=not_a_quarter_end, strict=True)

        assert dates[0].strftime("%d-%m-%Y") in str(refused.value)


def test_sealing_locks_for_good_and_defaults_to_the_latest_scheduled_date(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        expected = sealable(client)[-1]

        event = books.sign_off(client, senior, strict=True)

        assert event.action == BooksAction.SIGNED_OFF and event.through_date == expected
        assert Client.objects.get(pk=client.pk).signed_off_through == expected


def test_a_change_after_approval_blocks_the_seal_until_approved_again(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        editing.revise_in_place(entries(client).first(), Treatment(ledger=ledger(client, "Rent")), actor=staff.user)

        with pytest.raises(books.NotApprovedError) as refused:
            books.sign_off(client, senior, strict=True)
        assert "changed since the senior approved" in str(refused.value)

        books.approve(client, senior)
        books.sign_off(client, senior, strict=True)


def test_reopening_a_seal_withdraws_the_approval(client, staff, senior, posted):
    with firm_context(client.firm_id):
        request_and_approve(client, staff, senior)
        books.sign_off(client, senior, strict=True)

        books.reopen(client, senior, note="A late invoice")

        assert books.status(client).approved_through is None
