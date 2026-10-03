"""The rows placed in a ledger, and whether each has reached the books.

The ledger list says "rows placed" and the books hold posted entries in one financial year, so a
ledger could show rows placed and nothing under it. This list is what reconciles the two.
"""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_api import V1, ledger
from classify.engine import review, review_queue
from classify.models import LedgerGroup
from classify.treatment import Treatment
from core.db.session import firm_context
from core.models import Role
from core.provisioning import create_client
from ledger.approval import approve

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def url(client_record, ledger_row):
    return f"{V1}/clients/{client_record.pk}/ledgers/{ledger_row.pk}/rows/"


def test_a_placed_row_is_listed_and_says_whether_it_is_posted(api, senior, client_record, statement):
    misc = ledger(client_record, "Miscellaneous Expenses")
    with firm_context(client_record.firm_id):
        rows = list(review_queue(client_record)[:3])
        for row in rows:
            review(row, Treatment(ledger=misc), learn=False)
        approve(rows[0], membership=senior)

    body = api.get(url(client_record, misc)).json()

    assert body["count"] == 3
    by_id = {r["id"]: r for r in body["results"]}
    assert by_id[str(rows[0].pk)]["is_posted"] is True
    assert by_id[str(rows[1].pk)]["is_posted"] is False and by_id[str(rows[2].pk)]["is_posted"] is False
    first = by_id[str(rows[0].pk)]
    assert first["financial_year"] in (2024, 2025, 2026)
    assert first["amount_display"].startswith("₹") and first["narration"]


def test_rows_come_newest_first(api, client_record, statement):
    misc = ledger(client_record, "Miscellaneous Expenses")
    with firm_context(client_record.firm_id):
        for row in list(review_queue(client_record)):
            review(row, Treatment(ledger=misc), learn=False)

    dates = [r["value_date"] for r in api.get(url(client_record, misc)).json()["results"]]

    assert dates == sorted(dates, reverse=True) and len(dates) > 3


def test_only_rows_in_that_ledger_are_listed(api, client_record, statement):
    misc = ledger(client_record, "Miscellaneous Expenses")
    other = ledger(client_record, "Office Expenses")
    with firm_context(client_record.firm_id):
        rows = list(review_queue(client_record)[:4])
        for row in rows[:3]:
            review(row, Treatment(ledger=misc), learn=False)
        review(rows[3], Treatment(ledger=other), learn=False)

    assert api.get(url(client_record, misc)).json()["count"] == 3
    assert api.get(url(client_record, other)).json()["count"] == 1


def test_a_ledger_of_another_client_is_not_found(api, firm, client_record, statement):
    stranger = create_client(firm, "Someone Else", client_record.books_start if hasattr(client_record, "books_start") else __import__("datetime").date(2025, 4, 1))
    theirs = ledger(stranger, "Theirs", LedgerGroup.INDIRECT_EXPENSE)

    response = api.get(url(client_record, theirs))

    assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_a_long_ledger_costs_a_fixed_number_of_queries(api, client_record, statement, django_assert_max_num_queries):
    """Posting state is read from prefetched entries, so the cost does not grow with the rows."""
    misc = ledger(client_record, "Miscellaneous Expenses")
    with firm_context(client_record.firm_id):
        for row in list(review_queue(client_record)):
            review(row, Treatment(ledger=misc), learn=False)

    with django_assert_max_num_queries(25):
        response = api.get(url(client_record, misc) + "?page_size=500")

    assert response.status_code == 200 and response.json()["count"] > 10


def test_someone_who_cannot_view_transactions_is_refused(firm, client_record, statement, monkeypatch):
    """The ledger list is open to anyone who can see the client; narrations are not."""
    misc = ledger(client_record, "Miscellaneous Expenses")
    reader = member(firm, Role.READ_ONLY, "reader2@example.test")
    monkeypatch.setattr("api.views.classify.has_permission", lambda membership, permission: permission != "transaction.view")

    response = sign_in(reader.user).get(url(client_record, misc))

    assert response.status_code == 403
