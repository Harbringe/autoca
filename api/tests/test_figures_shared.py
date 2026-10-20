"""The overview and alerts are shared for a few seconds between requests, and a person's own change is seen at once."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.tests.conftest import member, sign_in
from core.db.session import firm_context
from core.models import Role
from core.provisioning import create_client, create_firm
from ledger.overview import firm_overview

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


@pytest.fixture(autouse=True)
def sharing_on(settings):
    settings.FRESHNESS_TTL = 60


def test_the_second_ask_for_the_overview_costs_no_queries(senior, client_record, django_assert_num_queries):
    with firm_context(senior.firm_id):
        first = firm_overview(senior)
        with django_assert_num_queries(0):
            second = firm_overview(senior)
    assert first == second and first["totals"]["clients"] == 1


def test_a_second_request_for_the_alerts_does_less_work_and_says_the_same(api, client_record, statement):
    with CaptureQueriesContext(connection) as first:
        one = api.get(f"{V1}/firm/alerts/").json()
    with CaptureQueriesContext(connection) as second:
        two = api.get(f"{V1}/firm/alerts/").json()
    assert one == two and one["alerts"]  # there is something to say, and it is the same
    assert len(second) < len(first)
    # Another module filter of the same feed shares the same work.
    with CaptureQueriesContext(connection) as filtered:
        bank = api.get(f"{V1}/firm/alerts/", {"module": "bank"}).json()
    assert len(filtered) <= len(second) and all(a["module"] == "bank" for a in bank["alerts"])


def test_a_persons_own_change_is_seen_at_once_whatever_is_remembered(firm, client_record, django_capture_on_commit_callbacks):
    admin = sign_in(member(firm, Role.FIRM_ADMIN, "fresh-admin@example.test").user)
    before = admin.get(f"{V1}/firm/overview/").json()
    assert before["totals"]["clients"] == 1
    assert admin.get(f"{V1}/firm/overview/").json() == before  # remembered

    # The forgetting is scheduled for after the change commits; a test's own transaction never commits, so its callbacks are run here.
    with django_capture_on_commit_callbacks(execute=True):
        created = admin.post(f"{V1}/clients/", {"name": "Second Client", "fy_start": "2026-04-01"}, format="json")
    assert created.status_code == 201, created.content

    after = admin.get(f"{V1}/firm/overview/").json()
    assert after["totals"]["clients"] == 2  # not the remembered 1: the change made it forget


def test_one_firm_never_reads_what_was_remembered_for_another(firm, client_record):
    other = create_client(create_firm("Another Firm"), "Their Only Client", datetime.date(2025, 4, 1))
    mine = sign_in(member(firm, Role.FIRM_ADMIN, "mine-admin@example.test").user)
    theirs = sign_in(member(other.firm, Role.FIRM_ADMIN, "theirs-admin@example.test").user)
    assert [c["name"] for c in mine.get(f"{V1}/firm/overview/").json()["clients"]] == ["Acme Traders"]
    assert [c["name"] for c in theirs.get(f"{V1}/firm/overview/").json()["clients"]] == ["Their Only Client"]
    assert [c["name"] for c in mine.get(f"{V1}/firm/overview/").json()["clients"]] == ["Acme Traders"]


def test_a_changed_client_alert_is_seen_at_once_too(firm, client_record, statement, django_capture_on_commit_callbacks):
    admin = sign_in(member(firm, Role.FIRM_ADMIN, "alerts-admin@example.test").user)
    mine = f"{V1}/clients/{client_record.pk}/alerts/"
    before = admin.get(mine).json()
    assert before["alerts"]
    assert admin.get(mine).json() == before
    with django_capture_on_commit_callbacks(execute=True):
        paused = admin.post(f"{V1}/clients/{client_record.pk}/assistant/pause/")  # any successful change through the API
    assert paused.status_code == 200
    with CaptureQueriesContext(connection) as worked_out_again:
        admin.get(mine)
    with CaptureQueriesContext(connection) as remembered:
        admin.get(mine)
    assert len(worked_out_again) > len(remembered)


def test_a_second_person_reuses_the_work_already_done_for_the_first(firm, client_record, statement):
    """The costly part is per client, not per person: ten people opening the app must not cost ten computations."""
    first = sign_in(member(firm, Role.FIRM_ADMIN, "first-share@example.test").user)
    second = sign_in(member(firm, Role.SENIOR_CA, "second-share@example.test").user)
    with CaptureQueriesContext(connection) as one:
        mine = first.get(f"{V1}/firm/alerts/").json()
    with CaptureQueriesContext(connection) as two:
        theirs = second.get(f"{V1}/firm/alerts/").json()
    assert mine["alerts"] and mine == theirs  # the same client's alerts, for each of them
    assert len(two) < len(one)
