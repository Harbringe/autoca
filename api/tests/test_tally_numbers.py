"""Tally's own voucher number is shown beside ours, on the entries an import wrote."""

from __future__ import annotations

import datetime

import pytest

from api.tests.test_tally_vouchers_api import (  # noqa: F401  (fixtures and helpers)
    V1,
    chart,
    post_run,
    sale,
    upload,
)
from classify.models import LedgerGroup as G
from core.db.session import firm_context
from ledger.tests.support import make_ledger, post

pytestmark = pytest.mark.django_db


def entries(api, client):
    data = api.get(f"{V1}/journal-entries/?client={client.pk}").json()
    return data["results"] if isinstance(data, dict) else data


def test_an_imported_entry_carries_its_tally_number_and_type(api, firm, client_record, chart):
    run = upload(api, client_record, [sale("g1", "138")]).json()
    post_run(api, client_record, run["id"])
    [entry] = [e for e in entries(api, client_record) if e["tally_number"]]
    assert (entry["tally_number"], entry["tally_type"]) == ("138", "Sales")
    assert entry["entry_no"] == 1, "our own number is untouched"


def test_an_entry_not_from_tally_has_empty_tally_fields(api, firm, client_record, chart):
    with firm_context(firm.pk):
        post(client_record, datetime.date(2025, 4, 5), make_ledger(client_record, "Rent", G.INDIRECT_EXPENSE), make_ledger(client_record, "Cash", G.CASH), 100)
    [entry] = entries(api, client_record)
    assert (entry["tally_number"], entry["tally_type"]) == ("", "")
