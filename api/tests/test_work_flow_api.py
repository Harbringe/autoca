"""``GET /api/v1/firm/work-flow/``: statement rows received against entries finished, week by week."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from api.tests.conftest import member, sign_in
from api.tests.work_support import assign, aware, post_entry, scoped
from banking.models import StatementTransaction
from core.db.session import firm_context
from core.models import Role
from core.provisioning import create_client, create_firm
from documents.models import Document

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

URL = "/api/v1/firm/work-flow/"
WINDOW = {"from": "2026-09-07", "to": "2026-09-27"}  # three weeks, Monday to Sunday


def _upload_time(client_record, statement, when):
    with firm_context(client_record.firm_id):
        Document.objects.filter(statement=statement).update(created_at=when)
        return StatementTransaction.objects.filter(statement=statement).count()


def _by_week(body):
    return {w["week_start"]: w for w in body["weekly"]}


def test_weeks_count_rows_received_and_entries_finished(api, senior, client_record, statement):
    rows = _upload_time(client_record, statement, aware(2026, 9, 15))
    post_entry(client_record, by=senior, at=aware(2026, 9, 9))
    post_entry(client_record, by=senior, at=aware(2026, 9, 22))
    post_entry(
        client_record, by=None, at=aware(2026, 9, 23)
    )  # the assistant's entry still counts for the firm
    post_entry(client_record, by=senior, at=aware(2026, 8, 20))  # the period before

    response = api.get(URL, WINDOW)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["scope"] == "firm" and body["period"] == {"from": "2026-09-07", "to": "2026-09-27"}
    weeks = _by_week(body)
    assert list(weeks) == ["2026-09-07", "2026-09-14", "2026-09-21"]
    assert weeks["2026-09-07"] == {"week_start": "2026-09-07", "received": 0, "finished": 1}
    assert weeks["2026-09-14"]["received"] == rows and weeks["2026-09-14"]["finished"] == 0
    assert weeks["2026-09-21"] == {"week_start": "2026-09-21", "received": 0, "finished": 2}
    assert body["totals"] == {
        "received": rows,
        "finished": 3,
        "prev_received": 0,
        "prev_finished": 1,
    }


def test_the_previous_period_has_the_same_length_and_ends_the_day_before(
    api, senior, client_record, statement
):
    rows = _upload_time(client_record, statement, aware(2026, 8, 17))
    post_entry(
        client_record, by=senior, at=aware(2026, 9, 6, hour=23)
    )  # the last day before the window
    post_entry(client_record, by=senior, at=aware(2026, 8, 16))  # one day too early

    totals = api.get(URL, WINDOW).json()["totals"]

    assert totals == {"received": 0, "finished": 0, "prev_received": rows, "prev_finished": 1}


def test_a_correcting_entry_is_not_finished_work(api, senior, client_record):
    original = post_entry(client_record, by=senior, at=aware(2026, 9, 9))
    post_entry(client_record, by=senior, at=aware(2026, 9, 10), corrects=original)

    assert api.get(URL, WINDOW).json()["totals"]["finished"] == 1


def test_the_default_period_is_the_last_twelve_weeks(api, client_record):
    body = api.get(URL).json()

    weeks = [w["week_start"] for w in body["weekly"]]
    assert len(weeks) == 12
    today = timezone.localdate()
    assert weeks[-1] == str(today - datetime.timedelta(days=today.weekday()))
    assert all(datetime.date.fromisoformat(w).weekday() == 0 for w in weeks)
    assert body["period"]["to"] == str(today)


def test_a_bad_period_is_refused_in_words(api):
    reversed_ = api.get(URL, {"from": "2026-09-27", "to": "2026-09-07"})
    assert reversed_.status_code == 400 and "from" in reversed_.json()["fields"]
    too_long = api.get(URL, {"from": "2025-01-01", "to": "2026-01-02"})
    assert too_long.status_code == 400 and "366" in str(too_long.json()["fields"]["to"])
    assert api.get(URL, {"from": "2025-01-01", "to": "2025-12-31"}).status_code == 200
    assert api.get(URL, {"from": "yesterday"}).status_code == 400
    assert api.get(URL, {"scope": "everyone"}).status_code == 400


def test_a_member_who_sees_only_some_clients_gets_those_whatever_scope_they_ask_for(
    firm, client_record, senior
):
    mine = client_record
    other = create_client(firm, "Not On My Team", datetime.date(2025, 4, 1))
    lead_member = scoped(member(firm, Role.SENIOR_CA, "team-lead@example.test"))
    assign(mine, lead_member)
    post_entry(mine, by=senior, at=aware(2026, 9, 9))
    post_entry(other, by=senior, at=aware(2026, 9, 9))
    post_entry(other, by=senior, at=aware(2026, 9, 10))
    http = sign_in(lead_member.user)

    for scope in ("team", "firm"):
        body = http.get(URL, {**WINDOW, "scope": scope}).json()
        assert body["scope"] == "team" and body["totals"]["finished"] == 1

    # An administrator sees the whole firm.
    admin = sign_in(member(firm, Role.FIRM_ADMIN, "owner@example.test").user)
    body = admin.get(URL, WINDOW).json()
    assert body["scope"] == "firm" and body["totals"]["finished"] == 3


def test_staff_and_read_only_members_read_only_their_clients(
    firm, client_record, senior, staff, reader
):
    other = create_client(firm, "Someone Else's Client", datetime.date(2025, 4, 1))
    scoped(staff)
    scoped(reader)
    assign(client_record, staff)
    post_entry(client_record, by=senior, at=aware(2026, 9, 9))
    post_entry(other, by=senior, at=aware(2026, 9, 9))

    assert sign_in(staff.user).get(URL, WINDOW).json()["totals"]["finished"] == 1
    nothing = sign_in(reader.user).get(URL, WINDOW)
    assert nothing.status_code == 200 and nothing.json()["totals"]["finished"] == 0


def test_another_firms_work_never_appears(api, senior, client_record):
    stranger = create_client(create_firm("Other Firm"), "Stranger Ltd", datetime.date(2025, 4, 1))
    post_entry(stranger, by=None, at=aware(2026, 9, 9))
    post_entry(client_record, by=senior, at=aware(2026, 9, 9))

    assert api.get(URL, WINDOW).json()["totals"]["finished"] == 1


def test_it_needs_a_sign_in(client_record):
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code in (401, 403)
