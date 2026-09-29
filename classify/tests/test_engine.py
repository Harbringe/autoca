"""Rule matching, and the loop that makes the review queue shrink.

The scenario throughout is the real one: a firm uploads a client's first
statement, most rows land in the queue, and each row a person places takes its
siblings with it.
"""

from __future__ import annotations

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import (
    LEARNED_PRIORITY,
    classify_statement,
    reclassify_unresolved,
    review,
    rules_for,
    unresolved_for,
)
from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    Direction,
    LedgerAccount,
    LedgerGroup,
    MatchType,
    RuleSource,
    TransactionClassification,
)
from classify.narration import Channel, analyse, normalise
from classify.seeds import seed_client
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def client():
    import datetime

    firm = create_firm("Classify Test Firm")
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


@pytest.fixture
def statement(client):
    with firm_context(client.firm_id):
        yield ingest_fixture_statement(client).statement


def ledger(client, name, group=LedgerGroup.INDIRECT_EXPENSE):
    return LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name=name, group=group
    )


def queued_for(client, fragment):
    """One queued row whose narration contains ``fragment``."""
    return unresolved_for(client).filter(transaction__narration__icontains=fragment).first()


# ---------------------------------------------------------------------------
# First pass over an unseen client
# ---------------------------------------------------------------------------


def test_with_no_rules_every_row_queues_rather_than_guessing(client, statement):
    """Silence is the right first answer. A guessed ledger is worse than a blank."""
    result = classify_statement(statement)

    assert result.placed == 0
    assert result.queued == 54
    assert TransactionClassification.objects.filter(needs_review=True).count() == 54
    assert not TransactionClassification.objects.filter(ledger__isnull=False).exists()


def test_narration_facts_are_recorded_even_when_nothing_matched(client, statement):
    """The review screen shows why a row is where it is, without re-deriving it."""
    classify_statement(statement)
    row = queued_for(client, "100000000001")

    assert row.channel == Channel.UPI
    assert row.counterparty == "ZERODHA BROKING LIMIT"


def test_seeded_rules_place_what_the_bank_itself_did(client, statement):
    """Interest and charges mean the same thing in every set of books."""
    seed_client(client)
    result = classify_statement(statement)

    interest = TransactionClassification.objects.filter(channel=Channel.INTEREST)
    assert interest.count() == 4
    assert {row.ledger.name for row in interest} == {"Bank Interest Received"}
    assert result.placed == 4


# ---------------------------------------------------------------------------
# The learning loop
# ---------------------------------------------------------------------------


def test_placing_one_row_places_every_sibling(client, statement):
    """Nineteen identical cashback credits are one decision, not nineteen."""
    classify_statement(statement)
    cashback = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)

    before = unresolved_for(client).count()
    row = queued_for(client, "NPCI BHIM")
    review(row, cashback)

    placed = TransactionClassification.objects.filter(ledger=cashback)
    assert placed.count() == 9
    assert unresolved_for(client).count() == before - 9


def test_the_learned_rule_keys_on_the_payee_not_the_narration(client, statement):
    """A rule keyed on a narration matches one transaction and never fires again."""
    classify_statement(statement)
    broker = ledger(client, "ZERODHA", LedgerGroup.INVESTMENT)

    _, rule = review(queued_for(client, "100000000001"), broker)

    assert rule.match_type == MatchType.PARTY_EQUALS
    assert rule.pattern == normalise("ZERODHA BROKING LIMIT")
    assert rule.source == RuleSource.LEARNED
    assert "100000000001" not in rule.pattern


def test_a_learned_rule_takes_the_direction_of_the_row_it_came_from(client, statement):
    """"Future receipts from X" must not also catch payments to X."""
    classify_statement(statement)
    cashback = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    row = queued_for(client, "NPCI BHIM")

    _, rule = review(row, cashback)

    assert rule.direction == (Direction.DEBIT if row.transaction.is_debit else Direction.CREDIT)
    assert rule.just_created is True
    facts = analyse(row.transaction.narration)
    assert rule.matches(facts, row.transaction.is_debit)
    assert not rule.matches(facts, not row.transaction.is_debit)


def test_a_new_directional_rule_outranks_an_older_either_direction_rule_for_the_same_payee(client, statement):
    """A person's correction must not lose a tie to a rule learned before rules had a direction."""
    from classify.engine import first_matching_rule

    classify_statement(statement)
    old_target = ledger(client, "Old Target", LedgerGroup.INDIRECT_INCOME)
    corrected = ledger(client, "Corrected Target", LedgerGroup.INDIRECT_INCOME)
    row = queued_for(client, "NPCI BHIM")
    ClassificationRule.objects.create(
        firm_id=client.firm_id, client=client, ledger=old_target,
        match_type=MatchType.PARTY_EQUALS, pattern=normalise(row.counterparty),
        direction=Direction.ANY, source=RuleSource.LEARNED, priority=LEARNED_PRIORITY,
    )

    review(row, corrected)

    facts = analyse(row.transaction.narration)
    winner = first_matching_rule(facts, row.transaction.is_debit, rules_for(client))
    assert winner.ledger_id == corrected.pk


def test_a_learned_rule_carries_forward_to_the_next_statement(client, statement):
    """The payoff. Month two should need almost no review at all."""
    classify_statement(statement)
    cashback = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    review(queued_for(client, "NPCI BHIM"), cashback)

    next_statement = ingest_fixture_statement(
        client, data=b"%PDF-1.4 next month", filename="next.pdf"
    ).statement
    result = classify_statement(next_statement)

    assert result.placed == 0  # the rows themselves are deduplicated
    rules = rules_for(client)
    assert any(rule.ledger_id == cashback.pk for rule in rules)


def test_a_person_can_place_one_row_without_teaching_a_rule(client, statement):
    """A refund that happens to name a regular payee is not a pattern."""
    classify_statement(statement)
    one_off = ledger(client, "Refund Received", LedgerGroup.INDIRECT_INCOME)

    row = queued_for(client, "NPCI BHIM")
    _, rule = review(row, one_off, learn=False)

    assert rule is None
    assert TransactionClassification.objects.filter(ledger=one_off).count() == 1


def test_changing_your_mind_updates_the_rule_rather_than_adding_a_second(client, statement):
    classify_statement(statement)
    first_choice = ledger(client, "Office Expenses")
    second_choice = ledger(client, "Staff Welfare")

    review(queued_for(client, "Blinkit"), first_choice)
    row = TransactionClassification.objects.get(transaction__narration__icontains="Blinkit")
    review(row, second_choice)

    rules = ClassificationRule.objects.filter(pattern=normalise("Blinkit"))
    assert rules.count() == 1
    assert rules.first().ledger_id == second_choice.pk


def test_a_new_rule_never_overturns_a_persons_decision(client, statement):
    """Reclassification touches the queue only. Judgement is not up for revision."""
    classify_statement(statement)
    chosen = ledger(client, "Staff Welfare")
    other = ledger(client, "Office Expenses")

    row = queued_for(client, "Blinkit")
    review(row, chosen, learn=False)

    ClassificationRule.objects.create(
        firm_id=client.firm_id,
        client=client,
        ledger=other,
        match_type=MatchType.NARRATION_CONTAINS,
        pattern=normalise("Blinkit"),
        priority=9999,
    )
    reclassify_unresolved(client)

    row.refresh_from_db()
    assert row.ledger_id == chosen.pk


# ---------------------------------------------------------------------------
# Ordering between rules that both claim a row
# ---------------------------------------------------------------------------


def test_a_higher_priority_rule_wins(client, statement):
    """Between two rules that both claim a row, priority decides."""
    broad = ledger(client, "General Expenses")
    specific = ledger(client, "Brokerage")

    ClassificationRule.objects.create(
        firm_id=client.firm_id,
        client=client,
        ledger=broad,
        match_type=MatchType.CHANNEL_IS,
        pattern=Channel.UPI,
        priority=1,
    )
    ClassificationRule.objects.create(
        firm_id=client.firm_id,
        client=client,
        ledger=specific,
        match_type=MatchType.PARTY_EQUALS,
        pattern=normalise("ZERODHA BROKING LIMIT"),
        priority=9999,
    )

    classify_statement(statement)
    row = TransactionClassification.objects.get(
        transaction__narration__icontains="100000000001"
    )

    assert row.ledger_id == specific.pk


def test_a_sibling_clients_rule_does_not_classify_this_client(client, statement):
    """Rules do not travel between clients, even inside one firm.

    A rule names a ledger and a ledger belongs to one client, so a rule that
    reached a sibling would be booking this client's money into another
    client's books. There is no priority high enough to make that right.
    """
    from core.provisioning import create_client

    sibling = create_client(client.firm, "Sibling Client", client.fy_start)
    sibling_ledger = ledger(sibling, "Sibling Brokerage")
    ClassificationRule.objects.create(
        firm_id=client.firm_id,
        client=sibling,
        ledger=sibling_ledger,
        match_type=MatchType.CHANNEL_IS,
        pattern=Channel.UPI,
        priority=9999,
    )

    classify_statement(statement)

    placed = TransactionClassification.objects.filter(ledger=sibling_ledger)
    assert not placed.exists(), "a sibling client's rule reached into these books"


def test_direction_narrows_a_rule(client, statement):
    """Money out to a payee and money in from them are rarely the same ledger."""
    paid = ledger(client, "Broker Payments")
    received = ledger(client, "Broker Receipts", LedgerGroup.INDIRECT_INCOME)

    for target, direction in ((paid, Direction.DEBIT), (received, Direction.CREDIT)):
        ClassificationRule.objects.create(
            firm_id=client.firm_id,
            client=client,
            ledger=target,
            match_type=MatchType.CHANNEL_IS,
            pattern=Channel.INTEREST,
            direction=direction,
            priority=200,
        )

    classify_statement(statement)
    interest = TransactionClassification.objects.filter(channel=Channel.INTEREST)

    assert interest.count() == 4
    assert {row.ledger.name for row in interest} == {"Broker Receipts"}


def test_learned_rules_outrank_seeds(client, statement):
    seed_client(client)
    classify_statement(statement)

    assert all(
        rule.priority < LEARNED_PRIORITY
        for rule in ClassificationRule.objects.filter(source=RuleSource.SEED)
    )


def test_rule_hits_are_counted_per_firing_not_per_statement(client, statement):
    """Nine cashbacks is one rule and nine hits. Counting it as one hides usage."""
    classify_statement(statement)
    cashback = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    _, rule = review(queued_for(client, "NPCI BHIM"), cashback)

    rule.refresh_from_db()
    assert rule.hit_count == 8  # the reviewed row itself was placed by a person


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_classification_is_idempotent(client, statement):
    """Re-running after a rule change must not duplicate or overwrite."""
    classify_statement(statement)
    again = classify_statement(statement)

    assert again.total == 0
    assert TransactionClassification.objects.count() == 54


def test_a_resolved_row_leaves_the_queue(client, statement):
    classify_statement(statement)
    target = ledger(client, "Advance Tax", LedgerGroup.DUTIES_AND_TAXES)

    row = queued_for(client, "INTERNET TAX PAYMENT")
    review(row, target)

    row.refresh_from_db()
    assert not row.needs_review
    assert row.method == ClassificationMethod.REVIEWED
    assert row.reviewed_at is not None


def test_another_firm_sees_none_of_this(client):
    """Built without the shared fixture: it holds one firm's context open."""
    other = create_firm("Other Firm")
    with firm_context(client.firm_id):
        classify_statement(ingest_fixture_statement(client).statement)

    with firm_context(other.pk):
        assert TransactionClassification.objects.count() == 0
        assert ClassificationRule.objects.count() == 0
        assert LedgerAccount.objects.count() == 0
