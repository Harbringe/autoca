"""Working draft until signed off, permanent after.

The two halves of this file are the two halves of the rule. Before sign-off an
entry can be changed and removed, and none of it is lost: what it was is kept.
After sign-off the *database* refuses -- and these tests go to the database
directly, because a lock the application enforces is a lock an application bug
can lose.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction

from classify.engine import review, review_queue
from classify.models import TransactionClassification
from classify.treatment import Treatment
from core.db.session import firm_context
from core.models import Client, Role
from ledger import books, editing
from ledger.approval import approve_many
from ledger.models import BooksAction, BooksEvent, ChangeAction, EntryChange, JournalEntry, VoucherSequence
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    membership_for,
    senior,
    staff,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def posted(client, statement, senior):
    """Every row placed in one ledger and posted, so the books are a full draft."""
    with firm_context(client.firm_id):
        misc = ledger(client, "Miscellaneous Expenses")
        for row in list(review_queue(client)):
            review(row, Treatment(ledger=misc), learn=False)
        approve_many(list(review_queue(client)), membership=senior)
        assert review_queue(client).count() == 0
        yield misc


def entries(client):
    return JournalEntry.objects.filter(firm_id=client.firm_id, client=client).order_by(
        "entry_date", "entry_no"
    )


# ---------------------------------------------------------------------------
# Before sign-off: changeable, and nothing is lost
# ---------------------------------------------------------------------------


def test_an_unsigned_entry_can_be_removed_and_is_kept_in_the_change_log(client, senior, posted):
    with firm_context(client.firm_id):
        entry = entries(client).first()
        entry_id, lines = entry.pk, entry.lines.count()

        editing.remove_entry(entry, actor=senior.user, note="Wrongly booked")

        assert not JournalEntry.objects.filter(pk=entry_id).exists()
        change = EntryChange.objects.get(entry_id=entry_id)
        assert change.action == ChangeAction.REMOVED
        assert change.actor_id == senior.user_id
        assert len(change.before["lines"]) == lines == 2
        assert change.note == "Wrongly booked"


def test_a_removed_entrys_row_goes_back_to_the_queue(client, senior, posted):
    with firm_context(client.firm_id):
        entry = entries(client).first()
        transaction_id = entry.source_transaction_id
        editing.remove_entry(entry, actor=senior.user)

        waiting = review_queue(client).filter(transaction_id=transaction_id)
        assert waiting.count() == 1, "removing an entry must not make its transaction vanish"


def test_an_unsigned_entry_can_be_moved_to_another_ledger_and_the_old_state_kept(
    client, senior, posted
):
    with firm_context(client.firm_id):
        rent = ledger(client, "Rent")
        entry = entries(client).first()

        editing.revise_in_place(entry, Treatment(ledger=rent), actor=senior.user, note="It is rent")
        entry.refresh_from_db()

        names = {line.ledger_account.name for line in entry.lines.select_related("ledger_account")}
        assert "Rent" in names and "Miscellaneous Expenses" not in names
        assert sum(line.signed_paise for line in entry.lines.all()) == 0, "must still balance"
        change = EntryChange.objects.get(entry_id=entry.pk)
        assert change.action == ChangeAction.EDITED
        assert "Miscellaneous Expenses" in {line["ledger"] for line in change.before["lines"]}
        assert "Rent" in {line["ledger"] for line in change.after["lines"]}


def test_an_edit_is_a_persons_decision_so_it_is_reviewed(client, senior, posted):
    with firm_context(client.firm_id):
        entry = entries(client).first()
        editing.revise_in_place(entry, Treatment(ledger=ledger(client, "Rent")), actor=senior.user)
        row = TransactionClassification.objects.get(transaction_id=entry.source_transaction_id)
        assert row.method == "REVIEWED"
        assert row.ledger.name == "Rent"


# ---------------------------------------------------------------------------
# The review workflow
# ---------------------------------------------------------------------------


def test_approval_cannot_be_requested_while_rows_still_need_a_decision(client, staff, statement):
    with firm_context(client.firm_id):
        with pytest.raises(books.NotReadyError) as raised:
            books.request_review(client, staff)
        assert raised.value.waiting > 0


def test_a_normal_ca_can_request_approval_but_cannot_sign_off(client, staff, senior, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff, note="All done")
        assert books.status(client).review_pending

        with pytest.raises(PermissionDenied):
            books.sign_off(client, staff)


def test_a_request_cannot_be_made_twice(client, staff, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff)
        with pytest.raises(books.BooksError):
            books.request_review(client, staff)


def test_a_senior_can_return_the_books_with_a_reason(client, staff, senior, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff)
        with pytest.raises(books.BooksError):
            books.return_for_changes(client, senior, note="  ")

        books.return_for_changes(client, senior, note="Rent looks wrong")

        current = books.status(client)
        assert not current.review_pending
        assert current.returned_note == "Rent looks wrong"


def test_nothing_can_be_signed_off_until_it_has_been_requested(client, senior, posted):
    with firm_context(client.firm_id):
        with pytest.raises(books.NothingRequestedError):
            books.sign_off(client, senior)


def test_a_removed_entry_means_approval_cannot_be_requested(client, staff, senior, posted):
    """The books are incomplete again the moment a row is back in the queue."""
    with firm_context(client.firm_id):
        editing.remove_entry(entries(client).first(), actor=senior.user)
        with pytest.raises(books.NotReadyError):
            books.request_review(client, staff)


# ---------------------------------------------------------------------------
# Sign-off: the lock, enforced by the database
# ---------------------------------------------------------------------------


def sign(client, staff, senior, **kwargs):
    books.request_review(client, staff)
    return books.sign_off(client, senior, **kwargs)


def test_signing_off_locks_the_books_through_the_latest_entry(client, staff, senior, posted):
    with firm_context(client.firm_id):
        latest = entries(client).last().entry_date

        event = sign(client, staff, senior)

        assert event.action == BooksAction.SIGNED_OFF
        assert books.status(client).signed_off_through == latest
        assert Client.objects.get(pk=client.pk).signed_off_through == latest


def test_a_signed_off_entry_cannot_be_edited_by_the_application(client, staff, senior, posted):
    with firm_context(client.firm_id):
        entry = entries(client).first()
        sign(client, staff, senior)

        with pytest.raises(editing.EntryLockedError):
            editing.remove_entry(entry, actor=senior.user)
        with pytest.raises(editing.EntryLockedError):
            editing.revise_in_place(entry, Treatment(ledger=ledger(client, "Rent")), actor=senior.user)


def test_the_database_refuses_to_change_or_delete_a_signed_off_entry(client, staff, senior, posted):
    """Past the application entirely -- raw SQL, as a bug or a person with access would."""
    with firm_context(client.firm_id):
        entry = entries(client).first()
        sign(client, staff, senior)

        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE ledger_journal_entry SET narration = 'x' WHERE id = %s", [entry.pk])
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ledger_journal_entry WHERE id = %s", [entry.pk])
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE ledger_journal_line SET amount_paise = amount_paise + 1 WHERE entry_id = %s",
                    [entry.pk],
                )
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM ledger_journal_line WHERE entry_id = %s", [entry.pk])


def test_the_database_refuses_a_new_entry_dated_inside_the_signed_off_period(
    client, staff, senior, posted
):
    with firm_context(client.firm_id):
        template = entries(client).first()
        sign(client, staff, senior)

        with pytest.raises(DatabaseError), transaction.atomic():
            JournalEntry.objects.create(
                firm_id=client.firm_id, client=client, entry_no=9999,
                financial_year=template.financial_year, entry_date=template.entry_date,
                voucher_type=template.voucher_type, approved_at=template.approved_at,
            )


def test_an_entry_cannot_be_edited_into_the_locked_period(client, staff, senior, posted):
    """Signing off through an earlier date leaves later entries free -- and fenced."""
    with firm_context(client.firm_id):
        all_entries = list(entries(client))
        first, later = all_entries[0], all_entries[-1]
        assert first.entry_date < later.entry_date
        sign(client, staff, senior, through=first.entry_date)

        with pytest.raises(DatabaseError), transaction.atomic():
            JournalEntry.objects.filter(pk=later.pk).update(entry_date=first.entry_date)


def test_entries_after_the_sign_off_date_stay_editable(client, staff, senior, posted):
    with firm_context(client.firm_id):
        all_entries = list(entries(client))
        first, later = all_entries[0], all_entries[-1]
        sign(client, staff, senior, through=first.entry_date)

        editing.revise_in_place(later, Treatment(ledger=ledger(client, "Rent")), actor=senior.user)

        assert EntryChange.objects.filter(entry_id=later.pk, action=ChangeAction.EDITED).exists()


def test_signing_off_needs_every_row_up_to_that_date_to_be_posted(client, staff, senior, posted):
    with firm_context(client.firm_id):
        books.request_review(client, staff)
        # Somebody removes an entry after the request was made.
        gone = entries(client).first()
        editing.remove_entry(gone, actor=senior.user)

        with pytest.raises(books.NotReadyError):
            books.sign_off(client, senior)


# ---------------------------------------------------------------------------
# Voucher numbers at sign-off
# ---------------------------------------------------------------------------


def test_voucher_numbers_are_contiguous_after_sign_off_however_many_were_deleted(
    client, staff, senior, posted
):
    with firm_context(client.firm_id):
        # Delete some entries, then post the rows again -- the sequence now has
        # holes and out-of-date-order numbers, as a real draft will.
        for entry in list(entries(client))[:3]:
            editing.remove_entry(entry, actor=senior.user)
        approve_many(list(review_queue(client)), membership=senior)

        sign(client, staff, senior)

        groups = {}
        for entry in entries(client):
            groups.setdefault((entry.financial_year, entry.voucher_type), []).append(entry)
        for (year, voucher_type), group in groups.items():
            numbers = sorted(e.entry_no for e in group)
            assert numbers == list(range(1, len(group) + 1)), (year, voucher_type, numbers)
            sequence = VoucherSequence.objects.get(
                client=client, financial_year=year, voucher_type=voucher_type
            )
            assert sequence.next_number == len(group) + 1
        # And numbers follow the dates, as vouchers in a signed book should.
        for group in groups.values():
            by_date = sorted(group, key=lambda e: (e.entry_date, e.entry_no))
            assert [e.entry_no for e in by_date] == sorted(e.entry_no for e in group)


# ---------------------------------------------------------------------------
# Reopening
# ---------------------------------------------------------------------------


def test_the_sign_off_date_cannot_be_moved_back_by_an_ordinary_update(client, staff, senior, posted):
    with firm_context(client.firm_id):
        sign(client, staff, senior)

        with pytest.raises(DatabaseError), transaction.atomic():
            Client.objects.filter(pk=client.pk).update(signed_off_through=None)
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE core_client SET signed_off_through = '2000-01-01' WHERE id = %s", [client.pk]
                )


def test_renaming_a_client_does_not_disturb_the_lock(client, staff, senior, posted):
    with firm_context(client.firm_id):
        sign(client, staff, senior)
        through = books.status(client).signed_off_through

        Client.objects.filter(pk=client.pk).update(name="Renamed")

        assert books.status(client).signed_off_through == through


def test_a_senior_can_reopen_the_books_with_a_reason_and_edit_again(client, staff, senior, posted):
    with firm_context(client.firm_id):
        entry = entries(client).first()
        sign(client, staff, senior)

        with pytest.raises(books.BooksError):
            books.reopen(client, senior, note="")

        books.reopen(client, senior, note="Auditor found an error")

        assert books.status(client).signed_off_through is None
        editing.revise_in_place(entry, Treatment(ledger=ledger(client, "Rent")), actor=senior.user)
        assert BooksEvent.objects.filter(client=client, action=BooksAction.REOPENED).count() == 1


def test_a_normal_ca_cannot_reopen(client, staff, senior, posted):
    with firm_context(client.firm_id):
        sign(client, staff, senior)
        with pytest.raises(PermissionDenied):
            books.reopen(client, staff, note="Please")


def test_a_second_sign_off_and_reopen_restores_the_first_date(client, staff, senior, posted):
    """Reopen undoes the latest sign-off only, however they interleave."""
    with firm_context(client.firm_id):
        all_entries = list(entries(client))
        first_date = all_entries[0].entry_date
        sign(client, staff, senior, through=first_date)
        # Post something new after the first sign-off, then sign that too.
        later = all_entries[-1]
        assert later.entry_date > first_date

        books.request_review(client, staff)
        books.sign_off(client, senior)
        assert books.status(client).signed_off_through == later.entry_date

        books.reopen(client, senior, note="One more look")

        assert books.status(client).signed_off_through == first_date
