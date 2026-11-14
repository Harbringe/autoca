"""Books brought from Tally have no asset register: their fixed-asset ledgers' openings and journals become one, by choice."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_bills import base
from classify.models import LedgerGroup
from core.db.session import firm_context
from ledger.models import LedgerOpening
from ledger.tests.support import make_ledger, post

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def tally_books(client_record):
    """Furniture brought forward at Rs 2,00,000, and a computer bought by journal (as Tally books it) for Rs 60,000."""
    with firm_context(client_record.firm_id):
        furniture = make_ledger(client_record, "Furniture & Fixtures", LedgerGroup.FIXED_ASSET)
        computers = make_ledger(client_record, "Computers", LedgerGroup.FIXED_ASSET)
        land = make_ledger(client_record, "Land", LedgerGroup.FIXED_ASSET)
        creditor = make_ledger(client_record, "Sample Computer House", LedgerGroup.CREDITOR)
        LedgerOpening.objects.create(
            firm_id=client_record.firm_id, client=client_record, ledger=furniture, financial_year=2025, signed_paise=2_00_000_00
        )
        LedgerOpening.objects.create(
            firm_id=client_record.firm_id, client=client_record, ledger=land, financial_year=2025, signed_paise=5_00_000_00
        )
        journal = post(client_record, datetime.date(2025, 7, 15), computers, creditor, 60_000_00)
    return {"furniture": furniture, "computers": computers, "land": land, "journal": journal}


def from_books(api, client_record):
    response = api.get(f"{base(client_record)}/assets/from-books/")
    assert response.status_code == 200, response.content
    return response.json()


def kinds(api, client_record):
    return {k["kind"]: k["count"] for k in api.get(f"{base(client_record)}/open-items/").json()["kinds"]}


def test_openings_and_journals_on_asset_ledgers_are_listed_with_a_suggested_rate(api, client_record, tally_books):
    rows = {r["ledger_name"]: r for r in from_books(api, client_record)}

    assert set(rows) == {"Furniture & Fixtures", "Computers", "Land"}
    assert rows["Furniture & Fixtures"]["source"] == "opening" and rows["Furniture & Fixtures"]["date"] == "2025-04-01"
    assert rows["Furniture & Fixtures"]["suggested_rate_bp"] == 1000
    assert rows["Computers"]["source"] == "entry" and rows["Computers"]["entry"] == str(tally_books["journal"].pk)
    assert rows["Computers"]["cost_paise"] == 60_000_00 and rows["Computers"]["suggested_rate_bp"] == 4000
    assert rows["Land"]["suggested_rate_bp"] == 0
    assert kinds(api, client_record)["fixed_asset_unregistered"] == 3


def test_an_asset_from_a_journal_cannot_cost_more_than_the_journal_put_there(api, client_record, tally_books):
    body = {
        "name": "Office computer", "ledger": str(tally_books["computers"].pk), "entry": str(tally_books["journal"].pk),
        "cost_paise": 60_000_01, "put_to_use": "2025-07-15", "method": "WDV_IT", "rate_bp": 4000,
    }
    over = api.post(f"{base(client_record)}/assets/", body, format="json")
    assert over.status_code == 422 and "at most" in over.json()["detail"]

    made = api.post(f"{base(client_record)}/assets/", {**body, "cost_paise": 60_000_00}, format="json")
    assert made.status_code == 201, made.content
    assert made.json()["entry"] == str(tally_books["journal"].pk)
    assert {r["ledger_name"] for r in from_books(api, client_record)} == {"Furniture & Fixtures", "Land"}


def test_register_all_takes_everything_but_land_and_clears_the_open_items(api, client_record, tally_books):
    made = api.post(f"{base(client_record)}/assets/from-books/register/")

    assert made.status_code == 201, made.content
    assert {(a["ledger_name"], a["method"], a["rate_bp"]) for a in made.json()} == {
        ("Furniture & Fixtures", "WDV_IT", 1000), ("Computers", "WDV_IT", 4000)
    }
    assert [r["ledger_name"] for r in from_books(api, client_record)] == ["Land"]
    assert kinds(api, client_record)["fixed_asset_unregistered"] == 1
    # The opening furniture is a full year in use; the computer, bought in July, is in use more than 180 days: full rate too.
    schedule = api.get(f"{base(client_record)}/assets/schedule/", {"fy": 2025}).json()
    charged = {r["asset"]["ledger_name"]: r["depreciation_paise"] for r in schedule["rows"]}
    assert charged == {"Furniture & Fixtures": 20_000_00, "Computers": 24_000_00}
