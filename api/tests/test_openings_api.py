"""An imported opening balance is broken into the bills it is made of, from the outside."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base, make_party
from classify.models import LedgerGroup, Party
from core.db.session import firm_context
from ledger.billing import party_ledger_for
from ledger.models import LedgerOpening

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

OWED = 5_000_00  # the client owes this supplier at 1 April 2025


@pytest.fixture
def ravi(api, client_record):
    """A supplier with an imported opening balance the client owes, and no bills."""
    party = make_party(api, client_record)
    with firm_context(client_record.firm_id):
        record = Party.objects.get(pk=party["id"])
        ledger = party_ledger_for(record, side=LedgerGroup.CREDITOR)
        LedgerOpening.objects.create(
            firm_id=client_record.firm_id, client=client_record, ledger=ledger, financial_year=2025, signed_paise=-OWED
        )
    return party


def opening(api, client_record, party):
    return api.get(f"{base(client_record)}/parties/{party['id']}/opening/")


def break_down(api, client_record, party, *bills):
    body = {"bills": [{"reference": r, "bill_date": d, "amount_paise": a} for r, d, a in bills]}
    return api.post(f"{base(client_record)}/parties/{party['id']}/opening-bills/", body, format="json")


def kinds(api, client_record):
    return {k["kind"]: k["count"] for k in api.get(f"{base(client_record)}/open-items/").json()["kinds"]}


def test_the_standing_says_what_is_owed_and_how_much_is_still_unexplained(api, client_record, ravi):
    standing = opening(api, client_record, ravi).json()

    assert standing["financial_year"] == 2025 and standing["direction"] == "CR"
    assert standing["opening_paise"] == OWED and standing["remaining_paise"] == OWED and standing["billed_paise"] == 0
    assert standing["opening_display"] == "₹5,000.00"


def test_until_it_is_broken_down_the_balance_is_an_open_item_and_the_party_does_not_reconcile(api, client_record, ravi):
    named = kinds(api, client_record)

    assert named["party_opening_unbilled"] == 1 and named["party_out_of_balance"] == 1


def test_breaking_the_balance_into_bills_makes_it_reconcile(api, client_record, ravi):
    response = break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 2_000_00), ("OLD-2", "2025-02-20", 3_000_00))

    assert response.status_code == 201, response.content
    assert response.json()["remaining_paise"] == 0 and response.json()["billed_paise"] == OWED
    named = kinds(api, client_record)
    assert named["party_opening_unbilled"] == 0 and named["party_out_of_balance"] == 0
    # They are real bills: they show as owing, aged from their own dates.
    owing = api.get(f"{base(client_record)}/outstanding/", {"side": "payables", "as_of": "2025-08-01"}).json()
    assert owing["total_paise"] == OWED
    assert [b["reference"] for b in owing["parties"][0]["bills"]] == ["OLD-1", "OLD-2"]


def test_a_part_breakdown_leaves_the_rest_visible(api, client_record, ravi):
    break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 2_000_00))

    assert opening(api, client_record, ravi).json()["remaining_paise"] == 3_000_00
    assert kinds(api, client_record)["party_opening_unbilled"] == 1


def test_bills_cannot_add_up_to_more_than_the_balance(api, client_record, ravi):
    response = break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 6_000_00))

    assert response.status_code == 422 and "cannot be exceeded" in response.json()["detail"]
    assert opening(api, client_record, ravi).json()["billed_paise"] == 0  # all or nothing


def test_a_bill_dated_in_the_year_the_balance_opens_is_refused(api, client_record, ravi):
    response = break_down(api, client_record, ravi, ("NEW-1", "2025-04-01", 1_000_00))

    assert response.status_code == 422 and "not before the balance" in response.json()["detail"]


def test_the_same_invoice_cannot_be_listed_twice(api, client_record, ravi):
    twice = break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 1_000_00), ("old-1", "2025-01-11", 1_000_00))
    assert twice.status_code == 422 and "twice" in twice.json()["detail"]

    break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 1_000_00))
    again = break_down(api, client_record, ravi, ("OLD-1", "2025-01-10", 1_000_00))
    assert again.status_code == 422 and "already listed" in again.json()["detail"]


def test_a_party_with_no_opening_balance_has_nothing_to_break_down(api, client_record):
    nobody = make_party(api, client_record, "No Opening", gstin="")

    response = break_down(api, client_record, nobody, ("OLD-1", "2025-01-10", 1_000_00))

    assert response.status_code == 422 and "no opening balance" in response.json()["detail"]


def test_a_read_only_member_may_read_the_standing_but_not_break_it_down(client_record, ravi, reader):
    viewer = sign_in(reader.user)

    assert opening(viewer, client_record, ravi).status_code == 200
    assert break_down(viewer, client_record, ravi, ("OLD-1", "2025-01-10", 1_000_00)).status_code == 403
