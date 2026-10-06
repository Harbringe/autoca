"""A ledger's group and name cannot be changed from under the books that rest on it."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def patch(api, client_record, ledger_id, body):
    return api.patch(f"{base(client_record)}/ledgers/{ledger_id}/", body, format="json")


def test_an_unused_ledger_can_be_regrouped_and_renamed(api, client_record):
    ledger = make_ledger(api, client_record, "Misc Costs", "INDIRECT_EXPENSE")

    assert patch(api, client_record, ledger["id"], {"group": "DIRECT_EXPENSE"}).status_code == 200
    assert patch(api, client_record, ledger["id"], {"name": "Misc Costs 2"}).status_code == 200


def test_a_ledger_with_entries_cannot_be_moved_to_another_group(api, client_record):
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    body = voucher(party, purchases, cgst_paise=0, sgst_paise=0, heads=[{"ledger": purchases["id"], "amount_paise": 1_000_00}])
    assert post_bill(api, client_record, body).status_code == 201

    moved = patch(api, client_record, purchases["id"], {"group": "INDIRECT_INCOME"})

    assert moved.status_code == 400 and "cannot change" in str(moved.json())
    # Saying the group it already has is not a change.
    assert patch(api, client_record, purchases["id"], {"group": purchases["group"]}).status_code == 200


def test_a_partys_own_account_is_not_renamed_or_regrouped_here(api, client_record):
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    body = voucher(party, purchases, cgst_paise=0, sgst_paise=0, heads=[{"ledger": purchases["id"], "amount_paise": 1_000_00}])
    post_bill(api, client_record, body)
    party = api.get(f"{base(client_record)}/parties/{party['id']}/").json()

    renamed = patch(api, client_record, party["ledger"], {"name": "Someone Else"})
    regrouped = patch(api, client_record, party["ledger"], {"group": "INDIRECT_INCOME"})

    assert renamed.status_code == 400 and regrouped.status_code == 400
    assert "party" in str(renamed.json())
