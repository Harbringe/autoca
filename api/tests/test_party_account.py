"""A party's own account in the books, opened on request: what lets a receipt from a person be booked to that person by name."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base
from classify.models import LedgerAccount, LedgerGroup, Party
from core.db.session import firm_context

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def make_party(api, client_record, name="Sample Person", role="CUSTOMER"):
    response = api.post(f"{base(client_record)}/parties/", {"canonical_name": name, "role": role}, format="json")
    assert response.status_code == 201, response.content
    return response.json()["id"]


def open_account(api, client_record, party_id):
    return api.post(f"{base(client_record)}/parties/{party_id}/account/")


def test_a_customers_account_is_opened_under_sundry_debtors_named_after_them(api, client_record):
    party_id = make_party(api, client_record)

    response = open_account(api, client_record, party_id)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["name"] == "Sample Person" and body["group"] == LedgerGroup.DEBTOR
    with firm_context(client_record.firm_id):
        assert str(Party.objects.get(pk=party_id).ledger_id) == body["id"]


def test_a_suppliers_account_is_under_sundry_creditors(api, client_record):
    response = open_account(api, client_record, make_party(api, client_record, "Sample Supplier", "VENDOR"))

    assert response.json()["group"] == LedgerGroup.CREDITOR


def test_asking_again_gives_the_same_account_and_makes_no_second_one(api, client_record):
    party_id = make_party(api, client_record)
    first = open_account(api, client_record, party_id).json()
    second = open_account(api, client_record, party_id).json()

    assert first["id"] == second["id"]
    with firm_context(client_record.firm_id):
        assert LedgerAccount.objects.filter(client=client_record, name="Sample Person").count() == 1


def test_an_account_the_client_already_has_under_that_name_is_adopted_not_duplicated(api, client_record):
    with firm_context(client_record.firm_id):
        existing = LedgerAccount.objects.create(firm_id=client_record.firm_id, client=client_record, name="Sample Person", group=LedgerGroup.DEBTOR)

    assert open_account(api, client_record, make_party(api, client_record)).json()["id"] == str(existing.pk)


def test_a_person_who_may_not_manage_parties_cannot_open_one(api, firm, client_record, reader):
    party_id = make_party(api, client_record)

    assert open_account(sign_in(reader.user), client_record, party_id).status_code == 403
