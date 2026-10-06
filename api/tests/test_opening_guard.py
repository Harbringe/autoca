"""An opening balance that contradicts the statement beginning on its date is refused unless it is confirmed on purpose."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def url(client_record, statement):
    return f"{V1}/clients/{client_record.pk}/bank-accounts/{statement.bank_account.pk}/opening-balance/"


def body(statement, paise, **extra):
    return {"opening_balance_paise": paise, "opening_as_of": statement.period_start.isoformat(), **extra}


def test_the_statements_own_opening_is_accepted(api, client_record, statement):
    response = api.post(url(client_record, statement), body(statement, statement.opening_balance_paise), format="json")

    assert response.status_code == 200, response.content


def test_a_flipped_sign_is_refused_and_says_so(api, client_record, statement):
    response = api.post(url(client_record, statement), body(statement, -statement.opening_balance_paise), format="json")

    assert response.status_code == 409 and response.json()["code"] == "opening_differs"
    assert "opposite sign" in response.json()["detail"]
    statement.bank_account.refresh_from_db()
    assert statement.bank_account.opening_balance_paise != -statement.opening_balance_paise


def test_a_different_amount_is_refused_with_the_difference(api, client_record, statement):
    response = api.post(url(client_record, statement), body(statement, statement.opening_balance_paise + 10_000_00), format="json")

    assert response.status_code == 409 and "differs by" in response.json()["detail"]


def test_a_difference_can_be_kept_on_purpose(api, client_record, statement):
    kept = body(statement, statement.opening_balance_paise + 10_000_00, acknowledge_difference=True)

    response = api.post(url(client_record, statement), kept, format="json")

    assert response.status_code == 200
    statement.bank_account.refresh_from_db()
    assert statement.bank_account.opening_balance_paise == statement.opening_balance_paise + 10_000_00


def test_an_opening_before_the_first_statement_is_not_compared(api, client_record, statement):
    response = api.post(
        url(client_record, statement), {"opening_balance_paise": 5_00_000_00, "opening_as_of": "2024-04-01"}, format="json"
    )

    assert response.status_code == 200
