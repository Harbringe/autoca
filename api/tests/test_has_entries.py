"""``has_entries`` on a client: the same fact that locks the financial year start (P-2a)."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from classify.treatment import ReviewBand
from core.models import Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def test_a_client_without_entries_says_so_in_the_list_and_the_detail(api, client_record):
    listed = api.get(f"{V1}/clients/").json()["results"]
    assert [c["has_entries"] for c in listed] == [False]
    assert api.get(f"{V1}/clients/{client_record.pk}/").json()["has_entries"] is False


def test_posting_an_entry_flips_it_and_the_year_start_is_then_locked(api, client_record, statement):
    posted = api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    assert posted.status_code == 201 and posted.json()

    assert api.get(f"{V1}/clients/{client_record.pk}/").json()["has_entries"] is True
    assert [c["has_entries"] for c in api.get(f"{V1}/clients/").json()["results"]] == [True]
    admin = sign_in(member(client_record.firm, Role.FIRM_ADMIN, "fy-admin@example.test").user)
    locked = admin.patch(f"{V1}/clients/{client_record.pk}/", {"fy_start": "2024-04-01"}, format="json")
    assert locked.status_code == 400


def test_the_list_answers_it_inside_the_one_query_not_one_per_client(api, firm, client_record):
    import datetime

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from core.provisioning import create_client

    for n in range(5):
        create_client(firm, f"Extra Client {n}", datetime.date(2025, 4, 1))
    with CaptureQueriesContext(connection) as queries:
        assert len(api.get(f"{V1}/clients/").json()["results"]) == 6
    assert sum('"ledger_journal_entry"' in q["sql"] for q in queries) == 1
