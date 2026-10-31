"""Posting every waiting month of a large file, oldest first."""

from __future__ import annotations

import datetime

import pytest

from core.models import Job
from ledger.models import LedgerImportRun
from ledger.tally_import import TallyOverlapError
from ledger.tally_jobs import KIND, enqueue_post_all
from ledger.tests.support import make_ledger, post
from ledger.tests.tally_voucher_xml import line, voucher
from ledger.tests.test_tally_read import (  # noqa: F401  (fixtures and helpers)
    G,
    chart,
    client,
    firm,
    member,
    read,
    sale,
    senior,
)

pytestmark = pytest.mark.django_db


def queued_runs():
    jobs = Job.objects.filter(kind=KIND).order_by("created_at")
    return [LedgerImportRun.objects.get(pk=j.payload["run"]).counts["date_from"] for j in jobs]


def test_post_all_queues_each_waiting_month_oldest_first(firm, client, senior, chart):
    read(client, senior, [sale("g3", "3", "20250601"), sale("g1", "1", "20250401"), sale("g2", "2", "20250502")])
    runs = enqueue_post_all(client, senior, senior.user, allow_overlap=False)
    assert len(runs) == 3
    assert queued_runs() == ["2025-04-01", "2025-05-02", "2025-06-01"]


def test_post_all_skips_a_month_with_nothing_to_post(firm, client, senior, chart):
    ghost = voucher(
        guid="gx", vtype="Sales", number="9", date="20250510", party="Nobody",
        lines=[line("Nobody", 100.0, party=True), line("Sales", -100.0)],
    )
    read(client, senior, [sale("g1", "1", "20250401"), ghost])
    assert len(enqueue_post_all(client, senior, senior.user, allow_overlap=False)) == 1
    assert queued_runs() == ["2025-04-01"]


def test_post_all_queues_nothing_when_any_month_has_entries_not_yet_agreed(firm, client, senior, chart):
    post(client, datetime.date(2025, 5, 5), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    read(client, senior, [sale("g1", "1", "20250401"), sale("g2", "2", "20250505")])
    with pytest.raises(TallyOverlapError):
        enqueue_post_all(client, senior, senior.user, allow_overlap=False)
    assert queued_runs() == []
    assert len(enqueue_post_all(client, senior, senior.user, allow_overlap=True)) == 2


def test_post_all_with_nothing_waiting_queues_nothing(firm, client, senior, chart):
    assert enqueue_post_all(client, senior, senior.user, allow_overlap=False) == []
