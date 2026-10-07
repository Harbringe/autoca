"""The small rules behind the dashboards that need no database."""

from __future__ import annotations

import datetime

from ledger import alerts as alerts_mod
from ledger import books
from ledger.dashboard import client_health
from ledger.workload import _task_order, week_start

D = datetime.date


def test_health_is_decided_in_one_place_and_overdue_wins():
    ok = {"months_missing": 0, "failing_controls": 0, "seal_due": None, "tds_overdue_paise": 0}
    assert client_health(**ok) == "on_track"
    assert client_health(**{**ok, "months_missing": 1}) == "at_risk"
    assert client_health(**{**ok, "failing_controls": 2}) == "at_risk"
    assert client_health(**{**ok, "seal_due": D(2026, 9, 30)}) == "at_risk"
    assert client_health(**{**ok, "tds_overdue_paise": 1}) == "overdue"
    assert client_health(**{**ok, "tds_overdue_paise": 1, "months_missing": 3}) == "overdue"


def _status(through, changed=0):
    return books.BooksStatus(
        signed_off_through=None,
        review_pending=False,
        approved_through=through,
        changed_since_approval=changed,
    )


def test_ready_to_seal_needs_approval_through_the_date_and_no_change():
    due = D(2026, 9, 30)
    assert books.ready_to_seal(_status(D(2026, 9, 30)), due) is True
    assert books.ready_to_seal(_status(D(2026, 10, 15)), due) is True
    assert books.ready_to_seal(_status(D(2026, 6, 30)), due) is False
    assert books.ready_to_seal(_status(D(2026, 9, 30), changed=1), due) is False
    assert books.ready_to_seal(_status(None), due) is False
    assert books.ready_to_seal(_status(D(2026, 9, 30)), None) is False


def _alert(kind, severity, due=None, client="Acme"):
    return alerts_mod.Alert(
        kind, severity, "bookkeeping", 1, client, "t", "d", "/x", {}, None, 1, due
    )


def test_overdue_is_critical_or_a_passed_sealing_date():
    assert alerts_mod.is_overdue(_alert("tds", "critical"))
    assert alerts_mod.is_overdue(_alert("seal", "high"))
    assert not alerts_mod.is_overdue(_alert("tds_due", "high"))
    assert not alerts_mod.is_overdue(_alert("review", "medium"))


def test_next_tasks_go_overdue_first_then_serious_then_earliest_due():
    review = _alert("review", "medium")
    due_soon = _alert("tds_due", "high", D(2026, 10, 10))
    due_later = _alert("tds_due", "high", D(2026, 10, 20))
    seal = _alert("seal", "high", D(2026, 9, 30))
    tds = _alert("tds", "critical", D(2026, 8, 7))

    ordered = sorted([review, due_later, seal, due_soon, tds], key=_task_order)

    assert ordered == [tds, seal, due_soon, due_later, review]


def test_weeks_start_on_monday():
    assert week_start(D(2026, 9, 14)) == D(2026, 9, 14)
    assert week_start(D(2026, 9, 20)) == D(2026, 9, 14)
    assert week_start(D(2026, 9, 21)) == D(2026, 9, 21)
