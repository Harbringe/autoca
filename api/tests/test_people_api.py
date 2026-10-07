"""``GET /api/v1/firm/people/``: five counts per team member, alphabetical, never a rank."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.tests.conftest import member, sign_in
from api.tests.work_support import assign, lead, post_entry, scoped
from core.db.session import firm_context, no_firm_context
from core.models import Role
from core.provisioning import create_client, create_firm
from ledger.models import BooksAction, BooksEvent

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
URL = f"{V1}/firm/people/"
KEYS = {
    "member_id",
    "name",
    "role",
    "assigned_clients",
    "open_items",
    "finished_in_period",
    "overdue",
    "waiting_on_others",
}


@pytest.fixture
def team(firm, client_record, statement):
    """An owner, a Senior CA with one staff member on their team, and a staff member on nobody's team.

    Client A (``client_record``, with a statement waiting) is led by the Senior and worked by staff 1. Client B is worked
    by staff 2. Staff 1 approved 3 entries on A, the Senior 1, the assistant 1; staff 2 approved 2 on B.
    """
    owner = member(firm, Role.FIRM_ADMIN, "a-owner@example.test")
    boss = scoped(member(firm, Role.SENIOR_CA, "b-lead@example.test"))
    staff1 = scoped(member(firm, Role.STAFF, "c-staff1@example.test"), manager=boss)
    staff2 = scoped(member(firm, Role.STAFF, "d-staff2@example.test"))
    client_b = create_client(firm, "Client B", datetime.date(2025, 4, 1))
    lead(client_record, boss)
    assign(client_record, staff1)
    assign(client_b, staff2)
    for _ in range(3):
        post_entry(client_record, by=staff1)
    post_entry(client_record, by=boss)
    post_entry(client_record, by=None)
    for _ in range(2):
        post_entry(client_b, by=staff2)
    with firm_context(firm.pk):
        BooksEvent.objects.create(firm=firm, client=client_record, action=BooksAction.REQUESTED)
    return {"owner": owner, "boss": boss, "staff1": staff1, "staff2": staff2, "client_b": client_b}


def _rows(http, **params):
    response = http.get(URL, params)
    assert response.status_code == 200, response.content
    return {r["name"]: r for r in response.json()["people"]}


def test_an_administrator_sees_everyone_alphabetically_with_each_count(team, client_record):
    http = sign_in(team["owner"].user)
    body = http.get(URL).json()
    names = [r["name"] for r in body["people"]]
    assert (
        names
        == sorted(names, key=str.lower)
        == [
            "a-owner@example.test",
            "b-lead@example.test",
            "c-staff1@example.test",
            "d-staff2@example.test",
        ]
    )
    assert all(set(r) == KEYS for r in body["people"])
    rows = {r["name"]: r for r in body["people"]}

    overview = http.get(f"{V1}/firm/overview/").json()["clients"]
    a = next(c for c in overview if c["id"] == str(client_record.pk))
    open_on_a = a["unresolved"] + a["pending_approval"] + a["ai_unchecked"]
    waiting_on_a = len(a["months_missing"]) + 1  # the books are with the senior
    assert open_on_a > 0

    owner = rows["a-owner@example.test"]
    assert owner["role"] == "FIRM_ADMIN"
    assert [
        owner[k]
        for k in (
            "assigned_clients",
            "open_items",
            "finished_in_period",
            "overdue",
            "waiting_on_others",
        )
    ] == [0] * 5
    staff1 = rows["c-staff1@example.test"]
    assert staff1["role"] == "STAFF" and staff1["assigned_clients"] == 1
    assert staff1["open_items"] == open_on_a and staff1["waiting_on_others"] == waiting_on_a
    assert staff1["finished_in_period"] == 3
    # Entries dated in 2025 on a quarterly client whose books were never sealed: a sealing date has passed.
    assert staff1["overdue"] == 1

    boss = rows["b-lead@example.test"]  # leads client A without being assigned to it
    assert boss["assigned_clients"] == 1 and boss["finished_in_period"] == 1
    assert boss["open_items"] == open_on_a and boss["overdue"] == 1

    staff2 = rows["d-staff2@example.test"]
    assert staff2["assigned_clients"] == 1 and staff2["finished_in_period"] == 2
    assert staff2["open_items"] == 0 and staff2["waiting_on_others"] == 0


def test_finished_follows_the_period_and_open_items_ignore_it(team):
    http = sign_in(team["owner"].user)

    rows = _rows(http, **{"from": "2020-01-01", "to": "2020-01-31"})

    assert rows["c-staff1@example.test"]["finished_in_period"] == 0
    assert rows["c-staff1@example.test"]["open_items"] > 0


def test_a_senior_sees_themselves_and_their_own_team_only(team):
    rows = _rows(sign_in(team["boss"].user))

    assert sorted(rows) == ["b-lead@example.test", "c-staff1@example.test"]
    assert rows["c-staff1@example.test"]["finished_in_period"] == 3


def test_a_senior_never_learns_of_clients_outside_their_own(team, firm):
    # Staff 1 is also put on client B, which the senior neither leads nor works.
    assign(team["client_b"], team["staff1"])
    post_entry(team["client_b"], by=team["staff1"])

    rows = _rows(sign_in(team["boss"].user))

    assert rows["c-staff1@example.test"]["assigned_clients"] == 1
    assert rows["c-staff1@example.test"]["finished_in_period"] == 3


def test_staff_and_read_only_members_are_refused(team, firm):
    reader = member(firm, Role.READ_ONLY, "e-reader@example.test")

    assert sign_in(team["staff1"].user).get(URL).status_code == 403
    assert sign_in(reader.user).get(URL).status_code == 403


def test_another_firms_people_and_work_never_appear(team):
    # The fixture leaves its own firm's context active; a second firm can only be built with none.
    with no_firm_context():
        other = create_firm("Other Firm")
        stranger_client = create_client(other, "Stranger Ltd", datetime.date(2025, 4, 1))
        stranger = member(other, Role.STAFF, "z-stranger@example.test")
        assign(stranger_client, stranger)
        post_entry(stranger_client, by=stranger)

    rows = _rows(sign_in(team["owner"].user))

    assert "z-stranger@example.test" not in rows
    assert (
        sum(r["finished_in_period"] for r in rows.values()) == 6
    )  # the stranger's entry is not among them


def test_a_deactivated_member_is_not_listed(team, firm):
    from core.models import FirmMembership

    with firm_context(firm.pk):
        FirmMembership.objects.filter(pk=team["staff2"].pk).update(is_active=False)

    assert "d-staff2@example.test" not in _rows(sign_in(team["owner"].user))


def test_a_bad_period_is_refused(team):
    http = sign_in(team["owner"].user)

    assert http.get(URL, {"from": "2026-02-01", "to": "2026-01-01"}).status_code == 400
    assert http.get(URL, {"from": "2024-01-01", "to": "2026-01-01"}).status_code == 400
    assert http.get(URL, {"to": "soon"}).status_code == 400


def test_more_people_cost_no_more_queries(team, firm):
    http = sign_in(team["owner"].user)
    http.get(URL)  # warm any per-process caches
    with CaptureQueriesContext(connection) as before:
        assert http.get(URL).status_code == 200
    for n in range(5):
        member(firm, Role.STAFF, f"extra{n}@example.test")
    with CaptureQueriesContext(connection) as after:
        response = http.get(URL)
    assert len(response.json()["people"]) == 9
    assert len(after) == len(before)
