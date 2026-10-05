"""One firm, two clients: their books must not touch.

Row-level security is firm-scoped, which is the right boundary for the thing
it defends against -- one firm reading another firm's data is impossible in
the database, whatever the application does. Inside a firm it can say nothing:
two clients of the same firm are the same tenant to Postgres.

So the separation between clients is application logic, and application logic
is exactly what rots without a test. A ledger belongs to one client. A rule
that places a transaction into a ledger therefore has to belong to the same
client as the ledger it names, or one client's money lands in another
client's books -- the two sets of books that a CA firm's whole liability
rests on being separate.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError

from classify.engine import rules_for
from classify.models import (
    ClassificationRule,
    Direction,
    LedgerAccount,
    LedgerGroup,
    MatchType,
    Party,
)
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_clients():
    """Two clients of the *same* firm -- the case RLS cannot see."""
    firm = create_firm("One CA Firm")
    with firm_context(firm.pk):
        alice = create_client(firm, "Alice Traders", datetime.date(2026, 4, 1))
        bob = create_client(firm, "Bob Industries", datetime.date(2026, 4, 1))
        yield firm, alice, bob


def _check_constraints_now():
    """Make the deferred keys fire on the statement instead of at commit.

    The composite keys are DEFERRABLE INITIALLY DEFERRED so that deleting a
    party, which Django handles by nulling the reference first, does not trip
    them mid-cascade. A test runs inside a transaction that is rolled back and
    never commits, so without this the violation would have nowhere to surface.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def _ledger(firm, client, name):
    return LedgerAccount.objects.create(
        firm_id=firm.pk, client=client, name=name, group=LedgerGroup.INDIRECT_EXPENSE
    )


def test_a_rule_may_not_place_one_clients_rows_in_another_clients_ledger(two_clients):
    firm, alice, bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")

    rule = ClassificationRule(
        firm_id=firm.pk,
        client=bob,
        ledger=alice_ledger,
        match_type=MatchType.PARTY_CONTAINS,
        pattern="acme",
        direction=Direction.ANY,
    )
    with pytest.raises(ValidationError) as caught:
        rule.full_clean()
    message = str(caught.value).lower()
    assert "another client" in message
    # And it does not say *which* client. Staff are assigned per client, so
    # naming the owner would disclose an engagement the caller is not on.
    assert "alice" not in message


def test_a_firm_wide_rule_may_not_name_a_clients_ledger(two_clients):
    """A firm-wide rule applies to every client, so its ledger cannot be one client's."""
    firm, alice, _bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")

    rule = ClassificationRule(
        firm_id=firm.pk,
        client=None,
        ledger=alice_ledger,
        match_type=MatchType.PARTY_CONTAINS,
        pattern="zenith",
        direction=Direction.ANY,
    )
    with pytest.raises(ValidationError):
        rule.full_clean()


def test_a_rule_may_not_name_another_clients_party(two_clients):
    firm, alice, bob = two_clients
    bob_ledger = _ledger(firm, bob, "Bob Expenses")
    alice_party = Party.objects.create(
        firm_id=firm.pk, client=alice, canonical_name="Alice's Supplier"
    )

    rule = ClassificationRule(
        firm_id=firm.pk,
        client=bob,
        ledger=bob_ledger,
        party=alice_party,
        match_type=MatchType.PARTY_CONTAINS,
        pattern="supplier",
        direction=Direction.ANY,
    )
    with pytest.raises(ValidationError):
        rule.full_clean()


def test_a_rule_within_one_client_is_fine(two_clients):
    """The guard must not break the ordinary case."""
    firm, _alice, bob = two_clients
    bob_ledger = _ledger(firm, bob, "Bob Expenses")

    rule = ClassificationRule(
        firm_id=firm.pk,
        client=bob,
        ledger=bob_ledger,
        match_type=MatchType.PARTY_CONTAINS,
        pattern="acme",
        direction=Direction.ANY,
    )
    rule.full_clean()
    rule.save()
    assert rule.pk


def test_one_clients_rules_never_reach_another_clients_classifier(two_clients):
    """``rules_for`` is what the engine walks. It must not carry Alice's rules to Bob."""
    firm, alice, bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")
    ClassificationRule.objects.create(
        firm_id=firm.pk,
        client=alice,
        ledger=alice_ledger,
        match_type=MatchType.PARTY_CONTAINS,
        pattern="acme",
        direction=Direction.ANY,
    )

    for rule in rules_for(bob):
        assert rule.ledger.client_id == bob.pk, (
            f"rule {rule.pattern!r} would place Bob's rows into "
            f"{rule.ledger.name!r}, a ledger owned by {rule.ledger.client.name}"
        )


def test_the_database_refuses_it_even_without_full_clean(two_clients):
    """``clean`` is a courtesy. The composite foreign key is the guarantee.

    ``objects.create`` never calls ``full_clean``, and neither does DRF's
    ``ModelSerializer``. If the only check lived in Python, the next code path
    written would skip it without anyone noticing. This asserts the check the
    application cannot walk past.
    """
    from django.db import IntegrityError, transaction

    firm, alice, bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _check_constraints_now()
            ClassificationRule.objects.create(
                firm_id=firm.pk,
                client=bob,
                ledger=alice_ledger,
                match_type=MatchType.PARTY_CONTAINS,
                pattern="acme",
                direction=Direction.ANY,
            )


def test_the_database_refuses_another_clients_party(two_clients):
    from django.db import IntegrityError, transaction

    firm, alice, bob = two_clients
    bob_ledger = _ledger(firm, bob, "Bob Expenses")
    alice_party = Party.objects.create(
        firm_id=firm.pk, client=alice, canonical_name="Alice's Supplier"
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _check_constraints_now()
            ClassificationRule.objects.create(
                firm_id=firm.pk,
                client=bob,
                ledger=bob_ledger,
                party=alice_party,
                match_type=MatchType.PARTY_CONTAINS,
                pattern="supplier",
                direction=Direction.ANY,
            )


def test_the_journal_refuses_a_line_in_another_clients_ledger(two_clients):
    """The books are the thing that must not merge, so the check is on them.

    A rule is one way a line could have reached the wrong client's ledger, and
    the composite key above closes it. This closes the destination itself: no
    code path, present or future, can write a line whose ledger belongs to a
    client other than the one whose entry it is.
    """
    import datetime as dt

    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from ledger.models import Direction as LineDirection
    from ledger.models import JournalEntry, JournalLine, VoucherType

    firm, alice, bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")

    entry = JournalEntry.objects.create(
        firm_id=firm.pk,
        client=bob,
        entry_no=1,
        financial_year=2026,
        entry_date=dt.date(2026, 4, 2),
        voucher_type=VoucherType.PAYMENT,
        narration="Being a payment that must not reach Alice's books",
        approved_at=timezone.now(),
    )

    with pytest.raises(IntegrityError) as caught:
        with transaction.atomic():
            JournalLine.objects.create(
                firm_id=firm.pk,
                entry=entry,
                ledger_account=alice_ledger,
                direction=LineDirection.DEBIT,
                amount_paise=100_00,
                signed_paise=100_00,
            )
    assert "another client" in str(caught.value)


def test_a_classification_cannot_name_another_clients_ledger(two_clients):
    """The table the leak actually landed in.

    Every route that places a transaction -- a rule, the model, a reviewer, a
    management command -- writes here. A check here covers all of them, and the
    ones not yet written.
    """
    from django.db import IntegrityError, transaction

    from classify.models import ClassificationMethod, TransactionClassification
    from core.tests.factories import _bank_account, _statement, _statement_transaction

    firm, alice, bob = two_clients
    alice_ledger = _ledger(firm, alice, "Alice Secret Project")

    account = _bank_account(firm, client=bob)
    txn = _statement_transaction(firm, statement=_statement(firm, bank_account=account))

    with pytest.raises(IntegrityError) as caught:
        with transaction.atomic():
            TransactionClassification.objects.create(
                firm_id=firm.pk,
                transaction=txn,
                ledger=alice_ledger,
                method=ClassificationMethod.REVIEWED,
                confidence=1.0,
                needs_review=False,
            )
    assert "another client" in str(caught.value)
