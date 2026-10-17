"""A person's decision is evidence with a strength, not an order.

One click on a payee is a hypothesis: it earns a rule that suggests, never one that posts on its own. A payee decided the same way again
and again earns more, still under the line at which the system posts without asking. A payee decided differently each time earns no
placing rule, and the newest click does not overwrite what the history says. (``classify.scoring`` is the arithmetic.)
"""

from __future__ import annotations

import pytest

from classify.engine import review
from classify.models import ClassificationRule, TransactionClassification
from classify.treatment import ReviewBand, Treatment
from core.db.session import firm_context
from ledger.approval import auto_post_client
from ledger.tests.test_ai_workflow import BHIM, client_filter, income, posted_for
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    senior,
    statement,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def bhim_rows(client):
    return list(TransactionClassification.objects.filter(client_filter(client), counterparty=BHIM).order_by("transaction__value_date"))


def rule_for(client):
    return ClassificationRule.objects.get(client=client, pattern="NPCIBHIM")


def test_one_decision_is_a_suggestion_and_never_a_rule_that_posts_on_its_own(client, statement):
    with firm_context(client.firm_id):
        right = income(client, "Cashback Received")
        first, *others = bhim_rows(client)
        review(first, Treatment(ledger=right))

        rule = rule_for(client)
        assert rule.is_active and rule.ledger_id == right.pk
        assert 0.75 <= rule.confidence <= 0.88, "enough to suggest, under the line at which a row posts itself"
        placed = list(TransactionClassification.objects.filter(pk__in=[o.pk for o in others], ledger=right))
        assert placed and all(r.review_band != ReviewBand.HIGH for r in placed)
        auto_post_client(client)
        assert posted_for(client, BHIM).count() == 0, "a rule learned from people's decisions never posts a row on its own"


def test_a_payee_decided_two_ways_earns_no_placing_rule(client, statement):
    with firm_context(client.firm_id):
        a, b = income(client, "Cashback Received"), income(client, "Sales Returns")
        rows = bhim_rows(client)
        review(rows[0], Treatment(ledger=a))
        assert rule_for(client).is_active
        review(rows[1], Treatment(ledger=b))
        assert not rule_for(client).is_active, "one each: nothing supports placing the next one on its own"


def test_a_payee_decided_the_same_way_again_and_again_earns_trust_but_stays_under_the_posting_line(client, statement):
    with firm_context(client.firm_id):
        right = income(client, "Cashback Received")
        rows = bhim_rows(client)
        for row in rows[:5]:
            review(row, Treatment(ledger=right))
        rule = rule_for(client)
        assert rule.is_active and rule.ledger_id == right.pk
        assert rule.confidence > 0.8
        assert rule.confidence <= 0.88


def test_the_latest_click_does_not_overwrite_what_most_decisions_said(client, statement):
    with firm_context(client.firm_id):
        right, other = income(client, "Cashback Received"), income(client, "Sales Returns")
        rows = bhim_rows(client)
        for row in rows[:5]:
            review(row, Treatment(ledger=right))
        before = rule_for(client).confidence
        review(rows[5], Treatment(ledger=other))
        rule = rule_for(client)
        assert rule.is_active and rule.ledger_id == right.pk, "five said Cashback Received, one said otherwise"
        assert rule.confidence <= before, "but the disagreement weakens what the rule claims"
