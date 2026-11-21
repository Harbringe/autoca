"""A bank's spelling of a supplier opened as its own account is merged into the account the books already have.

Everything of the duplicate goes across: its rows, the spellings it was recognised by, and its own name as one more spelling, so
the next statement finds the right account and opens nothing.
"""

from __future__ import annotations

import pytest

from api.tests.test_bills import base
from api.tests.test_party_account_placement import a_payment, supplier_account
from classify.models import (
    ClassificationMethod,
    ClassificationRule,
    LedgerAccount,
    MatchType,
    Party,
    PartyAlias,
    RuleSource,
)
from classify.parties import confirm_alias
from core.db.session import firm_context

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_a_duplicate_supplier_account_merges_into_the_one_in_the_books(api, client_record, statement):
    books = supplier_account(client_record, "Sample Silk Mill, Surat")
    duplicate = supplier_account(client_record, "Sample Silk Mills")
    row = a_payment(client_record)
    with firm_context(client_record.firm_id):
        row.ledger = duplicate
        row.party = duplicate.party_record
        row.method = ClassificationMethod.RULE
        row.confidence = 0.8
        row.save()
        confirm_alias(client_record, duplicate.party_record, "SAMPLE SILK MILLS SURAT")
        ClassificationRule.objects.create(
            firm_id=client_record.firm_id, client=client_record, match_type=MatchType.PARTY_EQUALS, pattern="SAMPLE SILK MILLS",
            ledger=duplicate, party=duplicate.party_record, source=RuleSource.LEARNED,
        )

    response = api.post(f"{base(client_record)}/ledgers/{duplicate.pk}/merge/", {"into": str(books.pk)}, format="json")

    assert response.status_code == 200, response.content
    row.refresh_from_db()
    keep = books.party_record
    assert row.ledger_id == books.pk and row.party_id == keep.pk
    with firm_context(client_record.firm_id):
        assert not LedgerAccount.objects.filter(pk=duplicate.pk).exists()
        assert not Party.objects.filter(canonical_name="Sample Silk Mills", client=client_record).exists()
        spellings = set(PartyAlias.objects.filter(party=keep).values_list("alias_display", flat=True))
        assert {"SAMPLE SILK MILLS SURAT", "Sample Silk Mills"} <= spellings
        rule = ClassificationRule.objects.get(client=client_record, pattern="SAMPLE SILK MILLS")
        assert rule.ledger_id == books.pk and rule.party_id == keep.pk


def test_a_party_account_does_not_merge_into_a_general_head(api, client_record, statement):
    duplicate = supplier_account(client_record, "Sample Silk Mills")
    with firm_context(client_record.firm_id):
        purchases = LedgerAccount.objects.create(firm_id=client_record.firm_id, client=client_record, name="Purchase 5%", group="PURCHASE")

    response = api.post(f"{base(client_record)}/ledgers/{duplicate.pk}/merge/", {"into": str(purchases.pk)}, format="json")

    assert response.status_code == 409
    assert "party's own account" in response.json()["detail"]
    assert LedgerAccount.objects.filter(pk=duplicate.pk).exists()


def test_the_ledger_list_says_which_are_a_partys_own_account(api, client_record):
    supplier_account(client_record, "Sample Fabrics")
    with firm_context(client_record.firm_id):
        LedgerAccount.objects.create(firm_id=client_record.firm_id, client=client_record, name="Purchase 5%", group="PURCHASE")
    ledgers = api.get(f"{base(client_record)}/ledgers/").json()
    ledgers = ledgers.get("results", ledgers)
    by_name = {ledger["name"]: ledger for ledger in ledgers}
    assert by_name["Sample Fabrics"]["is_party_account"] is True
    assert by_name["Purchase 5%"]["is_party_account"] is False


def test_placing_a_row_on_a_suppliers_account_remembers_the_spelling(api, client_record, statement):
    account = supplier_account(client_record, "Sample Fabrics")
    row = a_payment(client_record)
    with firm_context(client_record.firm_id):
        row.counterparty = "SAMPLE FABRICS TEXTILE MKT"
        row.save(update_fields=["counterparty"])

    response = api.post(
        f"/api/v1/classifications/{row.pk}/review/", {"ledger": str(account.pk), "party": None, "rcm": False, "tds_section": "", "learn": False}, format="json"
    )

    assert response.status_code in (200, 201), response.content
    row.refresh_from_db()
    assert row.party_id == account.party_record.pk
