"""The reporting dashboards: the firm portfolio and one client's snapshot."""

from __future__ import annotations

import datetime

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
PORTFOLIO = f"{V1}/firm/portfolio/"


def snapshot_url(client_record):
    return f"{V1}/clients/{client_record.pk}/dashboard/"


def test_a_new_client_has_a_portfolio_row_and_nothing_flagged(api, client_record):
    response = api.get(PORTFOLIO)

    assert response.status_code == 200, response.content
    body = response.json()
    (row,) = body["clients"]
    assert row["id"] == str(client_record.pk) and row["detail"] is True
    assert row["open_items"] == 0 and row["tds_overdue_paise"] == 0
    # A client with no entries owes no sealing, so the schedule must not flag it.
    assert row["seal_due"] is None
    assert body["attention"] == [] and body["detailed"] is True


def test_rows_waiting_in_review_are_flagged_for_the_client(api, client_record, statement):
    body = api.get(PORTFOLIO).json()

    kinds = {(a["kind"], a["client"]) for a in body["attention"]}
    assert ("review", str(client_record.pk)) in kinds
    # The row figures are the same ones the firm overview gives.
    overview = api.get(f"{V1}/firm/overview/").json()["clients"][0]
    assert body["clients"][0]["unresolved"] == overview["unresolved"]


def test_the_most_serious_attention_comes_first(api, client_record, statement):
    severities = [a["severity"] for a in api.get(PORTFOLIO).json()["attention"]]

    assert severities == sorted(severities, key={"critical": 0, "high": 1, "medium": 2}.get)


def test_the_snapshot_for_a_new_client_is_empty_but_complete(api, client_record):
    response = api.get(snapshot_url(client_record), {"fy": 2025})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["financial_year"] == 2025
    assert [m["month"] for m in body["trend"]][0] == "2025-04" and len(body["trend"]) == 12
    assert body["income_paise"] == 0 and body["profit_paise"] == 0 and body["top_expenses"] == []
    assert (
        body["owed"]["receivables"]["total_paise"] == 0
        and body["owed"]["payables"]["total_paise"] == 0
    )
    assert body["books"]["signed_off_through"] is None


def test_the_snapshot_lists_a_bank_account_with_its_ledger_balance(api, client_record, statement):
    body = api.get(snapshot_url(client_record), {"fy": 2025}).json()

    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["balance_display"].startswith(("₹", "-₹"))


def test_a_bad_year_says_what_to_send(api, client_record):
    response = api.get(snapshot_url(client_record), {"fy": "abc"})

    assert response.status_code == 400 and "fy" in response.json()["fields"]
    assert api.get(snapshot_url(client_record), {"fy": 1850}).status_code == 400


def test_staff_can_read_both(client_record, staff_api):
    assert staff_api.get(PORTFOLIO).status_code == 200
    assert staff_api.get(snapshot_url(client_record)).status_code == 200


def test_another_firms_client_is_not_found(api, client_record):
    from core.provisioning import create_client, create_firm

    stranger = create_client(create_firm("Other Firm"), "Stranger Ltd", datetime.date(2025, 4, 1))

    assert api.get(snapshot_url(stranger)).status_code == 404
