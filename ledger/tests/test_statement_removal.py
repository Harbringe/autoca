"""Taking back a statement uploaded by mistake."""

from __future__ import annotations

import pytest
from banking.models import Statement, StatementTransaction
from banking.removal import remove_statement
from classify.models import TransactionClassification
from core.db.session import firm_context
from core.models import Client
from core.rbac import Role, has_permission
from documents.models import Document
from ledger import editing
from ledger.approval import auto_post_client
from ledger.models import ChangeAction, EntryChange, JournalEntry
from ledger.tests.test_ai_workflow import BHIM, ai_places, income
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


def test_a_statement_nothing_was_posted_from_goes_entirely(client, staff, statement):
    with firm_context(client.firm_id):
        document_id = statement.document_id
        removed = remove_statement(statement, actor=staff.user)

        assert removed["entries"] == 0 and removed["rows"] > 0
        assert not Statement.objects.filter(pk=statement.pk).exists()
        assert not StatementTransaction.objects.filter(statement_id=statement.pk).exists()
        assert not TransactionClassification.objects.filter(
            transaction__statement_id=statement.pk
        ).exists()
        assert not Document.objects.filter(pk=document_id).exists()


def test_the_entries_the_ai_posted_from_it_go_with_it_and_are_logged(client, staff, statement):
    with firm_context(client.firm_id):
        ai_places(client, BHIM, income(client, "Cashback Received"))
        auto_post_client(client)
        posted = JournalEntry.objects.filter(client=client).count()
        assert posted >= 9

        removed = remove_statement(statement, actor=staff.user)

        assert removed["entries"] == posted
        assert JournalEntry.objects.filter(client=client).count() == 0
        assert EntryChange.objects.filter(action=ChangeAction.REMOVED).count() == posted


def test_signed_off_entries_stop_the_removal_and_nothing_is_touched(client, staff, statement):
    with firm_context(client.firm_id):
        rows = ai_places(client, BHIM, income(client, "Cashback Received"))
        auto_post_client(client)
        posted = JournalEntry.objects.filter(client=client).count()
        cutoff = max(r.transaction.value_date for r in rows)
        Client.objects.filter(pk=client.pk).update(signed_off_through=cutoff)

        with pytest.raises(editing.EntryLockedError):
            remove_statement(statement, actor=staff.user)

        assert Statement.objects.filter(pk=statement.pk).exists()
        assert JournalEntry.objects.filter(client=client).count() == posted


def test_staff_may_remove_a_statement_but_read_only_may_not():
    assert has_permission(_role(Role.STAFF), "statement.delete")
    assert not has_permission(_role(Role.READ_ONLY), "statement.delete")


def _role(role):
    class _Membership:
        pass

    m = _Membership()
    m.role = role
    m.is_active = True
    return m
