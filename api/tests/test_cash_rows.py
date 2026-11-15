"""A deposit or withdrawal at the counter is cash moving between the bank and the cash box, never a sale."""

from __future__ import annotations

import pytest

from api.tests.test_bills import make_ledger
from banking.models import StatementTransaction
from classify.engine import cash_ledger, reclassify_cash, review_queue
from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    LedgerAccount,
    MatchType,
    RuleSource,
)
from classify.narration import Channel, analyse
from core.db.session import firm_context

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.mark.parametrize("narration", ["BY CASH", "TO CASH SELF", "TO CASH", "CASH WITHDRAWAL", "by cash  ", "CASH DEPOSIT SELF"])
def test_the_narrations_a_bank_prints_for_cash_are_cash(narration):
    assert analyse(narration).channel == Channel.CASH


@pytest.mark.parametrize("narration", ["Chg Cash handling for:22-04-2025", "NEFT-X123-CASH CARRY TRADERS-0001", "BY CASH CREDIT SOCIETY LTD"])
def test_a_charge_or_a_payee_with_cash_in_its_name_is_not(narration):
    assert analyse(narration).channel != Channel.CASH


def test_a_cash_deposit_the_model_booked_to_sales_goes_to_the_cash_ledger(api, client_record, statement):
    sales = make_ledger(api, client_record, "Sales Cash Test", "SALES")
    with firm_context(client_record.firm_id):
        row = review_queue(client_record).filter(transaction__credit_paise__gt=0, is_self_transfer=False).first()
        StatementTransaction.objects.filter(pk=row.transaction_id).update(narration="BY CASH")
        row.ledger_id = sales["id"]
        row.method = ClassificationMethod.LLM
        row.confidence = 0.8
        row.save()

        assert reclassify_cash(client_record) == 1
        row.refresh_from_db()

    assert row.channel == Channel.CASH
    assert row.ledger.group == "CASH" and row.method == ClassificationMethod.RULE
    assert row.party_id is None and row.suggested_ledger_name == ""


def test_a_persons_choice_is_not_moved(api, client_record, statement):
    sales = make_ledger(api, client_record, "Sales Cash Test", "SALES")
    with firm_context(client_record.firm_id):
        row = review_queue(client_record).filter(transaction__credit_paise__gt=0, is_self_transfer=False).first()
        StatementTransaction.objects.filter(pk=row.transaction_id).update(narration="BY CASH")
        row.ledger_id = sales["id"]
        row.method = ClassificationMethod.REVIEWED
        row.save()

        assert reclassify_cash(client_record) == 0
        row.refresh_from_db()
    assert str(row.ledger_id) == sales["id"]


def test_the_clients_own_cash_ledger_beats_the_starter_and_the_rule_follows_it(api, client_record, statement):
    with firm_context(client_record.firm_id):
        starter = LedgerAccount.objects.get(client=client_record, name="Cash-in-Hand")
        theirs = LedgerAccount.objects.create(firm_id=client_record.firm_id, client=client_record, name="Cash", group="CASH")
        assert cash_ledger(client_record).pk == theirs.pk

        reclassify_cash(client_record)
        rule = ClassificationRule.objects.get(
            client=client_record, source=RuleSource.SEED, match_type=MatchType.CHANNEL_IS, pattern=Channel.CASH
        )
        assert rule.ledger_id == theirs.pk and rule.ledger_id != starter.pk
