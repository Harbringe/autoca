"""Alerts: what wants a person, where to click to fix it, and who may see which of it."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
FIRM = f"{V1}/firm/alerts/"


def client_url(client_record):
    return f"{V1}/clients/{client_record.pk}/alerts/"


def test_a_new_client_has_no_alerts(api, client_record):
    body = api.get(FIRM).json()

    assert body["alerts"] == []
    assert body["counts"]["total"] == 0 and body["counts"]["by_module"]["bank"] == 0


def test_rows_waiting_become_an_alert_that_opens_the_review_screen(api, client_record, statement):
    body = api.get(FIRM).json()

    rows = [a for a in body["alerts"] if a["kind"] == "review"]
    assert rows, body
    alert = rows[0]
    assert alert["module"] == "bank" and alert["client"] == str(client_record.pk)
    assert alert["to"] == f"/clients/{client_record.pk}/review"
    assert alert["search"] in ({"stage": "unresolved"}, {"stage": "pending_approval"})
    assert alert["count"] > 0 and alert["title"] and alert["detail"]


def test_the_module_filter_narrows_the_list_but_not_the_counts(api, client_record, statement):
    everything = api.get(FIRM).json()
    only_books = api.get(FIRM, {"module": "bookkeeping"}).json()

    assert all(a["module"] == "bookkeeping" for a in only_books["alerts"])
    assert only_books["counts"] == everything["counts"]
    assert everything["counts"]["total"] == len(everything["alerts"])


def test_an_unknown_module_says_what_to_send(api, client_record):
    response = api.get(FIRM, {"module": "nope"})

    assert response.status_code == 400 and "bank" in response.json()["fields"]["module"]


def test_the_most_serious_alert_comes_first(api, client_record, statement):
    order = {"critical": 0, "high": 1, "medium": 2}
    severities = [a["severity"] for a in api.get(FIRM).json()["alerts"]]

    assert severities == sorted(severities, key=order.get)


def test_one_client_feed_matches_the_firm_feed_for_that_client(api, client_record, statement):
    mine = api.get(client_url(client_record)).json()
    firm = [a for a in api.get(FIRM).json()["alerts"] if a["client"] == str(client_record.pk)]

    assert [a["kind"] for a in mine["alerts"]] == [a["kind"] for a in firm]


def test_the_portfolio_attention_list_carries_the_same_links(api, client_record, statement):
    attention = api.get(f"{V1}/firm/portfolio/").json()["attention"]

    assert attention and all(a["to"].startswith(f"/clients/{client_record.pk}") for a in attention)


def test_tds_alerts_are_left_out_for_a_caller_without_journal_view(api, client_record, monkeypatch):
    from api.views import dashboard as view

    monkeypatch.setattr(view, "has_permission", lambda membership, name: name != "journal.view")
    body = api.get(FIRM).json()

    assert not [a for a in body["alerts"] if a["kind"] in ("tds", "tds_due")]


def test_another_firms_client_is_not_found(api, client_record):
    import datetime

    from core.provisioning import create_client, create_firm

    stranger = create_client(create_firm("Other Firm"), "Stranger Ltd", datetime.date(2025, 4, 1))

    assert api.get(client_url(stranger)).status_code == 404
