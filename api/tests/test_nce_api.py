"""The financial statements in the ICAI non-corporate format, from the API."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def statements(api, client_record, fy=2025):
    response = api.get(f"{base(client_record)}/reports/financial-statements/", {"fy": fy})
    assert response.status_code == 200, response.content
    return response.json()


def by_key(rows):
    return {row["key"]: row for row in rows}


def book_purchase(api, client_record, amount=10_000_00):
    party = make_party(api, client_record, name="Ravi Traders")
    purchases = make_ledger(api, client_record, "Purchases", "PURCHASE")
    body = voucher(party, purchases, cgst_paise=0, sgst_paise=0, heads=[{"ledger": purchases["id"], "amount_paise": amount}])
    assert post_bill(api, client_record, body).status_code == 201
    return party


def test_the_balance_sheet_and_profit_and_loss_follow_the_icai_lines_and_balance(api, client_record):
    book_purchase(api, client_record)

    report = statements(api, client_record)

    bs, pl = by_key(report["balance_sheet"]), by_key(report["profit_and_loss"])
    assert bs["CL.PAY"]["current_paise"] == 10_000_00 and bs["CL.PAY"]["note"] == 9
    assert pl["PL.COGS"]["current_paise"] == 10_000_00 and pl["PL.COGS"]["note"] == 21
    assert pl["t.XVII"]["current_paise"] == -10_000_00  # a loss: purchases and no sales
    # The year's result is part of Reserves and surplus, so liabilities (with the loss) equal assets (nil).
    assert bs["EQ.RES"]["current_paise"] == -10_000_00
    assert bs["t.L"]["current_paise"] == bs["t.A"]["current_paise"] == 0
    assert report["balances"] is True


def test_each_line_is_taken_apart_in_its_note_by_ledger(api, client_record):
    book_purchase(api, client_record)

    report = statements(api, client_record)

    notes = {note["number"]: note for note in report["notes"]}
    assert [r["label"] for r in notes[9]["rows"]] == ["Ravi Traders"]
    assert notes[9]["total_current_paise"] == 10_000_00
    assert notes[21]["rows"][0]["current_paise"] == 10_000_00


def test_the_previous_year_is_beside_the_current_one(api, client_record):
    book_purchase(api, client_record)

    report = statements(api, client_record, fy=2026)

    bs = by_key(report["balance_sheet"])
    # The payable stands at the end of the previous year too, and is carried into this one.
    assert bs["CL.PAY"]["previous_paise"] == 10_000_00 and bs["CL.PAY"]["current_paise"] == 10_000_00
    assert report["has_previous"] is True


def test_a_ledger_can_be_placed_on_a_line_by_hand_and_a_wrong_line_is_refused(api, client_record):
    party = book_purchase(api, client_record)
    ledgers = api.get(f"{base(client_record)}/ledgers/").json()["results"]
    purchases = next(ledger for ledger in ledgers if ledger["name"] == "Purchases")

    refused = api.patch(f"{base(client_record)}/ledgers/{purchases['id']}/", {"nce_line": "NOPE"}, format="json")
    assert refused.status_code == 400

    done = api.patch(f"{base(client_record)}/ledgers/{purchases['id']}/", {"nce_line": "PL.EXP"}, format="json")
    assert done.status_code == 200, done.content
    pl = by_key(statements(api, client_record)["profit_and_loss"])
    assert pl["PL.EXP"]["current_paise"] == 10_000_00 and pl["PL.COGS"]["current_paise"] == 0
    assert party["id"]
