"""An accountant checking a learned rule can see the placed rows it rests on, and where each one went."""

from __future__ import annotations

import pytest

from classify.engine import review
from classify.models import ClassificationRule, MatchType
from classify.rule_evidence import evidence_for
from classify.treatment import Treatment
from core.db.session import firm_context
from ledger.tests.test_ai_workflow import income
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    senior,
    statement,
)
from ledger.tests.test_learning_by_proportion import bhim_rows, rule_for

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_the_evidence_counts_the_payees_rows_by_where_they_went(client, statement):
    with firm_context(client.firm_id):
        right, other = income(client, "Cashback Received"), income(client, "Sales Returns")
        rows = bhim_rows(client)
        for row in rows[:3]:
            review(row, Treatment(ledger=right))
        review(rows[3], Treatment(ledger=other))

        found = evidence_for(ClassificationRule.objects.get(pk=rule_for(client).pk))

    assert found["supported"] is True
    assert found["total"] >= 4
    assert found["to_this_ledger"] >= 3
    assert {"ledger": "Sales Returns", "count": 1} in found["elsewhere"]
    assert found["examples"] and all({"date", "narration", "paise", "ledger"} <= set(e) for e in found["examples"])


def test_a_rule_that_is_not_keyed_on_the_payee_has_no_evidence_to_show(client, statement):
    with firm_context(client.firm_id):
        rule = ClassificationRule.objects.create(
            firm_id=client.firm_id,
            client=client,
            ledger=income(client, "Cashback Received"),
            match_type=MatchType.NARRATION_CONTAINS,
            pattern="bhim",
        )
        assert evidence_for(rule) == {"supported": False}
