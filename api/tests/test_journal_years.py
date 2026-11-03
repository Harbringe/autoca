"""The Day Book and the year picker ask for one year, or only the list of years, instead of every voucher the client has."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_tally_vouchers_api import V1, chart  # noqa: F401  (fixtures and helpers)
from classify.models import LedgerAccount
from core.db.session import firm_context
from ledger.tests.support import post

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_years(firm, client_record, chart):  # noqa: F811
    with firm_context(firm.pk):
        cash = LedgerAccount.objects.get(client=client_record, name="Cash")
        sales = LedgerAccount.objects.get(client=client_record, name="Sales")
        post(client_record, datetime.date(2024, 6, 1), cash, sales, 100_00)
        post(client_record, datetime.date(2025, 7, 1), cash, sales, 200_00)
        post(client_record, datetime.date(2025, 8, 1), cash, sales, 300_00)
    return client_record


def test_the_years_a_client_has_vouchers_in_come_back_without_the_vouchers(api, two_years):
    response = api.get(f"{V1}/journal-entries/years/?client={two_years.pk}")

    assert response.status_code == 200
    assert response.json() == [2024, 2025]


def test_a_year_filter_returns_only_that_years_entries(api, two_years):
    rows = api.get(f"{V1}/journal-entries/?client={two_years.pk}&live=true&financial_year=2025").json()["results"]

    assert sorted(r["entry_date"] for r in rows) == ["2025-07-01", "2025-08-01"]


def test_a_year_that_is_not_a_number_is_refused(api, two_years):
    response = api.get(f"{V1}/journal-entries/?client={two_years.pk}&financial_year=next")

    assert response.status_code == 400
