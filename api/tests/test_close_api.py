"""The close page from the outside."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_the_report_has_its_controls_and_no_items_for_a_new_client(api, client_record):
    response = api.get(f"{base(client_record)}/books/close/")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ready"] is True and body["unexplained_blocking"] == 0 and body["items"] == []
    assert {c["name"] for c in body["checks"]} >= {"rows_posted", "assistant_entries_checked", "suspense_clear"}


def test_a_bad_date_says_what_to_send(api, client_record):
    response = api.get(f"{base(client_record)}/books/close/", {"through": "1-8-2025"})

    assert response.status_code == 400 and "YYYY-MM-DD" in response.json()["fields"]["through"][0]


def test_explaining_something_that_is_not_open_is_refused_with_a_reason(api, client_record):
    response = api.post(
        f"{base(client_record)}/books/close/explain/", {"item_key": "invoice_unbooked|invoice|nope", "note": "It can stand"}, format="json"
    )

    assert response.status_code == 422 and response.json()["code"] == "close_rule"


def test_staff_can_read_the_page_but_not_explain(client_record, staff_api):
    assert staff_api.get(f"{base(client_record)}/books/close/").status_code == 200
    denied = staff_api.post(
        f"{base(client_record)}/books/close/explain/", {"item_key": "x|y|z", "note": "It can stand"}, format="json"
    )
    assert denied.status_code == 403
