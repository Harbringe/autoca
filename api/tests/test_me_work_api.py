"""``GET /api/v1/me/work/``: a member's own clients, counts, daily series and next tasks. Own data only."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from api.tests.conftest import member, sign_in
from api.tests.work_support import assign, aware, lead, post_entry, scoped
from core.db.session import firm_context
from core.models import Role
from core.provisioning import create_client, create_firm
from ledger.models import BooksAction, BooksEvent

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
URL = f"{V1}/me/work/"
WINDOW = {"from": "2026-09-07", "to": "2026-09-13"}


@pytest.fixture
def meera(firm):
    return scoped(member(firm, Role.STAFF, "meera@example.test"))


def test_a_member_with_no_clients_gets_an_empty_but_complete_answer(meera, client_record):
    response = sign_in(meera.user).get(URL, WINDOW)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["period"] == {"from": "2026-09-07", "to": "2026-09-13"}
    assert [
        body[k]
        for k in ("assigned_clients", "open_items", "overdue", "waiting", "finished_in_period")
    ] == [0] * 5
    assert body["next_tasks"] == [] and body["clients"] == []
    assert [d["date"] for d in body["daily"]] == [f"2026-09-{day:02d}" for day in range(7, 14)]
    assert all(d["finished"] == 0 for d in body["daily"])


def test_the_counts_cover_the_members_own_clients_and_own_entries(
    firm, client_record, statement, meera, senior
):
    colleague = scoped(member(firm, Role.STAFF, "colleague@example.test"))
    other = create_client(firm, "Not Meera's", datetime.date(2025, 4, 1))
    assign(client_record, meera)
    assign(client_record, colleague)
    post_entry(client_record, by=meera, at=aware(2026, 9, 8))
    post_entry(client_record, by=meera, at=aware(2026, 9, 8, hour=15))
    post_entry(client_record, by=meera, at=aware(2026, 9, 11))
    post_entry(
        client_record, by=colleague, at=aware(2026, 9, 9)
    )  # a colleague's, on a shared client
    post_entry(client_record, by=meera, at=aware(2026, 9, 20))  # outside the period
    post_entry(other, by=senior, at=aware(2026, 9, 9))
    with firm_context(firm.pk):
        BooksEvent.objects.create(firm=firm, client=client_record, action=BooksAction.REQUESTED)

    http = sign_in(meera.user)
    body = http.get(URL, WINDOW).json()

    assert body["assigned_clients"] == 1 and body["finished_in_period"] == 3
    assert {d["date"]: d["finished"] for d in body["daily"]} == {
        "2026-09-07": 0,
        "2026-09-08": 2,
        "2026-09-09": 0,
        "2026-09-10": 0,
        "2026-09-11": 1,
        "2026-09-12": 0,
        "2026-09-13": 0,
    }
    overview = sign_in(senior.user).get(f"{V1}/firm/overview/").json()["clients"]
    mine = next(c for c in overview if c["id"] == str(client_record.pk))
    assert (
        body["open_items"]
        == mine["unresolved"] + mine["pending_approval"] + mine["ai_unchecked"]
        > 0
    )
    assert body["waiting"] == len(mine["months_missing"]) + 1
    assert body["overdue"] == 1
    assert body["clients"] == [
        {"id": str(client_record.pk), "name": "Acme Traders", "open_items": body["open_items"]}
    ]


def test_a_client_the_member_leads_counts_as_theirs(firm, client_record, senior):
    boss = scoped(member(firm, Role.SENIOR_CA, "boss@example.test"))
    lead(client_record, boss)

    body = sign_in(boss.user).get(URL, WINDOW).json()

    assert body["assigned_clients"] == 1 and [c["name"] for c in body["clients"]] == [
        "Acme Traders"
    ]


def test_next_tasks_put_what_is_overdue_first_and_say_where_to_go(
    firm, client_record, statement, meera, senior
):
    assign(client_record, meera)
    post_entry(client_record, by=senior, at=aware(2026, 9, 8))

    body = sign_in(meera.user).get(URL, WINDOW).json()

    tasks = body["next_tasks"]
    assert 1 < len(tasks) <= 8
    first = tasks[0]
    assert first["client"] == str(client_record.pk) and first["client_name"] == "Acme Traders"
    assert first["title"] == "Books are due to be sealed" and first["severity"] == "high"
    assert first["to"] == f"/clients/{client_record.pk}/books"
    due = datetime.date.fromisoformat(first["due"])
    assert due <= timezone.localdate()
    assert set(first) == {"client", "client_name", "title", "due", "to", "search", "severity"}
    assert all(t["client"] == str(client_record.pk) for t in tasks)


def test_it_shows_nothing_of_clients_the_member_is_not_on(firm, client_record, meera, senior):
    stranger = create_client(create_firm("Other Firm"), "Stranger Ltd", datetime.date(2025, 4, 1))
    post_entry(stranger, by=None)
    post_entry(client_record, by=senior)

    body = sign_in(meera.user).get(URL).json()

    assert body["assigned_clients"] == 0 and body["next_tasks"] == [] and body["clients"] == []


def test_every_role_may_ask_for_its_own_work(firm, client_record):
    for role in (Role.FIRM_ADMIN, Role.SENIOR_CA, Role.STAFF, Role.READ_ONLY):
        who = member(firm, role, f"{role.lower()}-me@example.test")
        assert sign_in(who.user).get(URL).status_code == 200


def test_a_bad_period_is_refused(meera):
    http = sign_in(meera.user)

    assert http.get(URL, {"from": "2026-09-13", "to": "2026-09-07"}).status_code == 400
    assert http.get(URL, {"from": "2024-01-01", "to": "2026-01-01"}).status_code == 400
    assert http.get(URL, {"from": "later"}).status_code == 400


def test_it_needs_a_sign_in():
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code in (401, 403)


def test_a_big_firm_does_not_blank_the_detail_of_a_member_with_few_clients(
    firm, client_record, senior, monkeypatch
):
    monkeypatch.setattr("ledger.workload.DETAIL_LIMIT", 1)
    create_client(firm, "Another Client", datetime.date(2025, 4, 1))
    boss = member(firm, Role.SENIOR_CA, "sees-all@example.test")  # sees every client, leads one
    lead(client_record, boss)
    post_entry(client_record, by=senior)

    body = sign_in(boss.user).get(URL).json()

    assert body["assigned_clients"] == 1 and body["overdue"] == 1
    assert body["next_tasks"][0]["title"] == "Books are due to be sealed"
