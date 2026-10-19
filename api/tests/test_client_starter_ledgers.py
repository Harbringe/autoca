"""A new client starts with the base and starter ledgers; seeding never overwrites a firm's own choice."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import SEED_LEDGERS, STARTER_LEDGERS, seed_starter_ledgers
from core.db.session import firm_context
from core.models import Client, Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_seeding_a_client_is_idempotent_and_leaves_a_ledger_of_the_same_name_alone(client_record, firm):
    with firm_context(firm.pk):
        LedgerAccount.objects.create(firm_id=firm.pk, client=client_record, name="Rent", group=LedgerGroup.DIRECT_EXPENSE)
        first = seed_starter_ledgers(client_record)
        second = seed_starter_ledgers(client_record)
        assert first == len(STARTER_LEDGERS) - 1 and second == 0
        assert LedgerAccount.objects.get(client=client_record, name="Rent").group == LedgerGroup.DIRECT_EXPENSE  # the firm's own choice stays
        assert LedgerAccount.objects.get(client=client_record, name="Sales").group == LedgerGroup.SALES


def test_a_client_created_through_the_api_starts_with_the_base_and_starter_ledgers(firm):
    http = sign_in(member(firm, Role.FIRM_ADMIN, "starter-admin@example.test").user)
    created = http.post("/api/v1/clients/", {"name": "Fresh Traders", "fy_start": "2026-04-01"}, format="json")
    assert created.status_code == 201, created.content
    with firm_context(firm.pk):
        client = Client.objects.get(name="Fresh Traders")
        have = set(LedgerAccount.objects.filter(client=client).values_list("name", flat=True))
    assert {name for name, _ in SEED_LEDGERS} <= have
    assert {name for name, _ in STARTER_LEDGERS} <= have
    assert len(have) == len(SEED_LEDGERS) + len(STARTER_LEDGERS)
