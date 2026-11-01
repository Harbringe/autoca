"""A large vouchers export is stored, read by a worker, and split into one queued import per month."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_background_upload import QuietBeat
from core import jobqueue
from core.db.session import firm_context
from core.models import Job, JobStatus
from ledger.models import ImportKind, ImportStatus, LedgerImportRun
from ledger.tally_read import enqueue_read
from ledger.tests.support import make_ledger, post
from ledger.tests.tally_voucher_xml import vouchers_xml
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    G,
    chart,
    client,
    firm,
    member,
    sale,
    senior,
)

pytestmark = pytest.mark.django_db


def read(client, senior, vouchers, **kw):
    """Queue the reading of a file and let the worker do it."""
    outcome = enqueue_read(client, senior, senior.user, data=vouchers_xml(vouchers, **kw), filename="year.xml", voucher_types=None)
    jobqueue.run_once("test-reader", heartbeat_factory=QuietBeat)
    return outcome


def runs(client):
    rows = LedgerImportRun.objects.filter(client=client, kind=ImportKind.VOUCHERS).order_by("counts__date_from")
    return list(rows)


def test_a_year_file_becomes_one_queued_import_per_month(firm, client, senior, chart):
    outcome = read(client, senior, [sale("g1", "1", "20250401"), sale("g2", "2", "20250415"), sale("g3", "3", "20250502")])
    job = Job.objects.get(pk=outcome.job.pk)
    assert job.status == JobStatus.SUCCEEDED and job.result["months"] == 2 and job.result["failed"] == []
    first, second = runs(client)
    assert (first.counts["date_from"], first.counts["will_post"]) == ("2025-04-01", 2)
    assert (second.counts["date_from"], second.counts["will_post"]) == ("2025-05-02", 1)
    assert first.status == ImportStatus.PREVIEW and first.document_id == second.document_id and first.document_id is not None


def test_the_same_big_file_twice_makes_no_new_runs(firm, client, senior, chart):
    vouchers = [sale("g1", "1", "20250401"), sale("g2", "2", "20250502")]
    read(client, senior, vouchers)
    again = read(client, senior, vouchers)
    assert again.reused is True and len(runs(client)) == 2


def test_a_file_read_again_after_its_imports_were_discarded_is_staged_afresh(firm, client, senior, chart):
    vouchers = [sale("g1", "1", "20250401")]
    read(client, senior, vouchers)
    LedgerImportRun.objects.filter(client=client).update(status=ImportStatus.DISCARDED)
    again = read(client, senior, vouchers)
    assert again.reused is False
    assert [r.status for r in runs(client)].count(ImportStatus.PREVIEW) == 1


def test_two_companies_refuse_the_whole_file(firm, client, senior, chart):
    outcome = enqueue_read(
        client,
        senior,
        senior.user,
        data=vouchers_xml([sale()], company="ONE").replace(b"</STATICVARIABLES>", b"<SVCURRENTCOMPANY>TWO</SVCURRENTCOMPANY></STATICVARIABLES>"),
        filename="year.xml",
        voucher_types=None,
    )
    jobqueue.run_once("test-reader", heartbeat_factory=QuietBeat)
    job = Job.objects.get(pk=outcome.job.pk)
    assert job.status == JobStatus.FAILED and "more than one company" in job.error
    assert runs(client) == []


def test_a_month_with_entries_still_gets_a_run_with_the_overlap_warning(firm, client, senior, chart):
    post(client, datetime.date(2025, 5, 5), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    read(client, senior, [sale("g1", "1", "20250401"), sale("g2", "2", "20250505")])
    april, may = runs(client)
    assert april.counts["existing_entries"] == 0 and may.counts["existing_entries"] == 1


def test_a_file_spanning_march_and_april_gets_the_right_financial_years(firm, client, senior, chart):
    read(client, senior, [sale("g1", "1", "20250328"), sale("g2", "2", "20250401")])
    march, april = runs(client)
    assert (march.financial_year, april.financial_year) == (2024, 2025)


def test_a_file_uploaded_again_while_it_is_still_being_read_is_the_same_job(firm, client, senior, chart):
    data = vouchers_xml([sale("g1", "1", "20250401")])
    first = enqueue_read(client, senior, senior.user, data=data, filename="year.xml", voucher_types=None)
    second = enqueue_read(client, senior, senior.user, data=data, filename="year.xml", voucher_types=None)
    assert second.reused is True and second.job.pk == first.job.pk
    assert Job.objects.filter(pk=first.job.pk).exists()


def test_the_read_job_is_finished_inside_its_firm_context(firm, client, senior, chart, monkeypatch):
    """The worker process has no ambient firm: the job row's last write is refused by the database unless it is made inside one."""
    from django.db import connection

    original = jobqueue.HANDLERS["tally.read"]

    def as_the_worker_would(ctx):
        with connection.cursor() as cursor:  # whatever the test left set, a real worker starts with nothing
            cursor.execute("select set_config('app.firm_id', '', true)")
        original(ctx)

    monkeypatch.setitem(jobqueue.HANDLERS, "tally.read", as_the_worker_would)
    outcome = read(client, senior, [sale("g1", "1", "20250401")])
    with firm_context(firm.pk):
        assert Job.objects.get(pk=outcome.job.pk).status == JobStatus.SUCCEEDED
