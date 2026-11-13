"""The whole-client Excel export, and the accounts opened for clear payees. Through the real stack, like the bill tests."""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _sheets(response):
    assert response.status_code == 200, response.content
    assert response["Content-Type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return load_workbook(io.BytesIO(response.content), read_only=True)


def test_export_has_a_sheet_for_each_kind_of_record_and_the_books_add_up(api, client_record):
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    assert post_bill(api, client_record, voucher(party, purchases)).status_code == 201

    book = _sheets(api.get(f"{base(client_record)}/reports/client-export/"))
    for name in ("Summary", "Ledgers", "Trial balance", "Bank accounts", "Bank transactions", "Vouchers", "Voucher lines", "Invoices", "Parties"):
        assert name in book.sheetnames
    lines = list(book["Voucher lines"].iter_rows(values_only=True))[1:]
    debit = sum(row[6] or 0 for row in lines)
    credit = sum(row[7] or 0 for row in lines)
    assert debit == credit and debit > 0
    assert len(list(book["Vouchers"].iter_rows(values_only=True))) - 1 == 1
    invoices = list(book["Invoices"].iter_rows(values_only=True))[1:]
    assert [row[3] for row in invoices] == ["INV-1"]


def test_text_typed_by_others_cannot_become_a_formula(api, client_record):
    make_party(api, client_record, name="=HYPERLINK(\"http://example.test\")")
    book = _sheets(api.get(f"{base(client_record)}/reports/client-export/"))
    names = [row[0] for row in list(book["Parties"].iter_rows(values_only=True))[1:]]
    assert names and all(not str(n).startswith("=") for n in names)


def test_the_export_is_refused_to_someone_who_cannot_see_the_client(client_record):
    from rest_framework.test import APIClient

    assert APIClient().get(f"{base(client_record)}/reports/client-export/").status_code in (401, 403)
