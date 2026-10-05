"""The AI fills the books; a CA corrects; the AI learns and applies it.

What matters here is what the AI is *not* allowed to do: post what it is unsure
of, park anything in Suspense, override a person, or touch signed-off books.
"""

from __future__ import annotations

import pytest

from classify.models import (
    ClassificationRule,
    LedgerGroup,
    TransactionClassification,
)
from classify.treatment import ReviewBand, Treatment
from core.db.session import firm_context
from core.models import Client
from ledger import books
from ledger.approval import approve, auto_post_client, correct
from ledger.learning import learn_from_decision
from ledger.models import ChangeAction, EntryChange, EntryMarker, JournalEntry
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

BHIM = "NPCI BHIM"


def income(client, name):
    return ledger(client, name, LedgerGroup.INDIRECT_INCOME)


def ai_places(client, counterparty, target, *, confidence=0.95, method="LLM", question=""):
    """Put the AI's placement on every row of a payee, as the model tier would."""
    rows = TransactionClassification.objects.filter(client_filter(client), counterparty=counterparty)
    rows.update(
        ledger=target, method=method, confidence=confidence,
        review_band=ReviewBand.HIGH if confidence >= 0.9 else ReviewBand.JUDGEMENT,
        needs_review=True, open_question=question,
    )
    return list(rows)


def client_filter(client):
    from django.db.models import Q

    return Q(firm_id=client.firm_id, transaction__bank_account__client=client)


def posted_for(client, counterparty):
    return JournalEntry.objects.filter(
        firm_id=client.firm_id,
        client=client,
        source_transaction__classification__counterparty=counterparty,
    )


# ---------------------------------------------------------------------------
# What the AI may post on its own
# ---------------------------------------------------------------------------


def test_the_ai_posts_what_it_is_very_sure_of_and_marks_it(client, statement):
    with firm_context(client.firm_id):
        ai_places(client, BHIM, income(client, "Cashback Received"))

        posted = auto_post_client(client)

        entries = posted_for(client, BHIM)
        assert posted >= entries.count() == 9
        for entry in entries:
            assert entry.approved_by_id is None, "nobody approved it; the AI posted it"
            assert entry.marker == EntryMarker.AI_POSTED


def test_a_guess_is_never_posted(client, statement):
    with firm_context(client.firm_id):
        ai_places(client, BHIM, income(client, "Cashback Received"), confidence=0.6)
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0


def test_a_row_the_model_asked_a_question_about_is_never_posted(client, statement):
    """A question means the model was not sure, whatever number it reported."""
    with firm_context(client.firm_id):
        ai_places(client, BHIM, income(client, "Cashback Received"), question="Is this a refund?")
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0


def test_the_ai_never_parks_an_entry_in_suspense(client, statement):
    with firm_context(client.firm_id):
        suspense = ledger(client, "Parking", LedgerGroup.SUSPENSE)
        ai_places(client, BHIM, suspense)
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0


def test_money_that_moved_by_upi_is_never_auto_posted_as_cash(client, statement):
    """A UPI transfer to the holder's other account once went in as "cash withdrawn" at 0.96."""
    with firm_context(client.firm_id):
        cash = ledger(client, "Petty Cash", LedgerGroup.CASH)
        rows = ai_places(client, BHIM, cash, confidence=0.96)
        TransactionClassification.objects.filter(pk__in=[r.pk for r in rows]).update(channel="UPI")
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0


def test_a_cash_withdrawal_at_the_counter_may_still_post_to_cash(client, statement):
    with firm_context(client.firm_id):
        cash = ledger(client, "Petty Cash", LedgerGroup.CASH)
        rows = ai_places(client, BHIM, cash, confidence=0.96)
        TransactionClassification.objects.filter(pk__in=[r.pk for r in rows]).update(channel="CASH")
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == len(rows)


def test_a_ledger_the_model_just_opened_waits_for_a_person_to_post_there_first(client, senior, statement):
    with firm_context(client.firm_id):
        opened = income(client, "Cashback Received")
        opened.proposal_reason = "No existing ledger fits cashback."
        opened.save(update_fields=["proposal_reason"])
        rows = ai_places(client, BHIM, opened)

        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0, "a new head is not trusted on the model's word"

        approve(rows[0], membership=senior)
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == len(rows), "once a person has used it, it is a head like any other"


def test_a_row_a_person_has_not_approved_is_not_posted_by_a_person_decision_alone(
    client, statement, senior
):
    """A person's placement still waits for their own approval; only the AI's is automatic."""
    with firm_context(client.firm_id):
        rows = ai_places(client, BHIM, income(client, "Cashback Received"))
        TransactionClassification.objects.filter(pk=rows[0].pk).update(method="REVIEWED")
        auto_post_client(client)
        assert not JournalEntry.objects.filter(source_transaction=rows[0].transaction).exists()


def test_auto_posting_twice_posts_nothing_the_second_time(client, statement):
    with firm_context(client.firm_id):
        ai_places(client, BHIM, income(client, "Cashback Received"))
        auto_post_client(client)
        assert auto_post_client(client) == 0


def test_the_ai_learns_nothing_from_its_own_posting(client, statement):
    with firm_context(client.firm_id):
        before = ClassificationRule.objects.count()
        ai_places(client, BHIM, income(client, "Cashback Received"))
        auto_post_client(client)
        assert ClassificationRule.objects.count() == before


def test_the_ai_will_not_post_into_signed_off_books(client, statement):
    with firm_context(client.firm_id):
        rows = ai_places(client, BHIM, income(client, "Cashback Received"))
        cutoff = max(r.transaction.value_date for r in rows)
        Client.objects.filter(pk=client.pk).update(signed_off_through=cutoff)

        assert auto_post_client(client) >= 0
        assert posted_for(client, BHIM).count() == 0


# ---------------------------------------------------------------------------
# Correcting one, and the AI applying it to the rest
# ---------------------------------------------------------------------------


def test_correcting_one_entry_moves_the_similar_ones_the_ai_placed(client, senior, statement):
    with firm_context(client.firm_id):
        wrong, right = income(client, "Wrong Income"), income(client, "Cashback Received")
        ai_places(client, BHIM, wrong)
        auto_post_client(client)
        entries = list(posted_for(client, BHIM))
        assert len(entries) == 9

        correct(entries[0], membership=senior, treatment=Treatment(ledger=right))

        for entry in posted_for(client, BHIM):
            names = {line.ledger_account.name for line in entry.lines.select_related("ledger_account")}
            assert "Cashback Received" in names and "Wrong Income" not in names
        others = posted_for(client, BHIM).exclude(pk=entries[0].pk)
        assert {e.marker for e in others} == {EntryMarker.AI_REVISED}, "what the AI moved is marked"
        assert EntryChange.objects.filter(action=ChangeAction.AI_REVISED).count() == 8
        assert entries[0].__class__.objects.get(pk=entries[0].pk).marker == EntryMarker.NONE


def test_the_correction_teaches_a_rule_for_the_next_statement(client, senior, statement):
    with firm_context(client.firm_id):
        right = income(client, "Cashback Received")
        ai_places(client, BHIM, income(client, "Wrong Income"))
        auto_post_client(client)

        correct(posted_for(client, BHIM).first(), membership=senior, treatment=Treatment(ledger=right))

        rule = ClassificationRule.objects.get(client=client, pattern="NPCIBHIM")
        assert rule.ledger_id == right.pk


def test_a_persons_own_decision_is_never_overridden_by_the_lesson(client, senior, statement):
    with firm_context(client.firm_id):
        wrong, right = income(client, "Wrong Income"), income(client, "Cashback Received")
        special = income(client, "Special Case")
        ai_places(client, BHIM, wrong)
        auto_post_client(client)
        entries = list(posted_for(client, BHIM))

        # A person deliberately puts one somewhere else...
        correct(entries[1], membership=senior, treatment=Treatment(ledger=special))
        # ...and then corrects another. The lesson must not undo their choice.
        correct(entries[0], membership=senior, treatment=Treatment(ledger=right))

        kept = {line.ledger_account.name for line in entries[1].lines.select_related("ledger_account")}
        row = TransactionClassification.objects.get(transaction=entries[1].source_transaction)
        assert row.method == "REVIEWED"
        assert row.ledger.name in ("Special Case", "Cashback Received")
        assert row.method == "REVIEWED", kept


def test_signed_off_entries_are_not_rewritten_by_a_later_lesson(client, staff, senior, statement):
    with firm_context(client.firm_id):
        wrong, right = income(client, "Wrong Income"), income(client, "Cashback Received")
        ai_places(client, BHIM, wrong)
        auto_post_client(client)
        entries = sorted(posted_for(client, BHIM), key=lambda e: e.entry_date)
        first, last = entries[0], entries[-1]
        assert first.entry_date < last.entry_date
        # Everything else waiting must be posted for the books to be signable.
        from classify.engine import review, review_queue
        from ledger.approval import approve_many

        misc = ledger(client, "Miscellaneous Expenses")
        for row in list(review_queue(client)):
            review(row, Treatment(ledger=misc), learn=False)
        approve_many(list(review_queue(client)), membership=senior)
        books.request_review(client, staff)
        with pytest.raises(books.AiEntriesUncheckedError):
            books.sign_off(client, senior, through=first.entry_date)
        # A person checks the assistant's entries, as sign-off requires.
        JournalEntry.objects.filter(client=client).update(marker=EntryMarker.NONE)
        books.sign_off(client, senior, through=first.entry_date)

        correct(last, membership=senior, treatment=Treatment(ledger=right))

        names = {line.ledger_account.name for line in first.lines.select_related("ledger_account")}
        assert "Wrong Income" in names, "signed-off books are never rewritten"


def test_placing_a_row_reports_what_the_lesson_changed(client, senior, statement):
    with firm_context(client.firm_id):
        right = income(client, "Cashback Received")
        rows = ai_places(client, BHIM, income(client, "Wrong Income"), confidence=0.6)
        target = rows[0]

        _, rule, revised, auto_posted = learn_from_decision(
            target, Treatment(ledger=right), user=senior.user
        )

        assert rule is not None
        assert revised == 8, "the other eight guesses moved to the ledger the person chose"
        assert auto_posted >= 8, "and, now rule-placed at 0.95, they post themselves"
