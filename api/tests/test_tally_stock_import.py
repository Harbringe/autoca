"""Bringing a client's stock items in from Tally's stock-item export: a preview, then the writing, safe to repeat."""

from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from api.tests.conftest import member, sign_in
from api.tests.test_bills import base
from core.models import Role
from ledger.tests.test_tally_stock import MUSTARD, xml

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def url(client):
    return f"{base(client)}/stock-items/import-tally/"


def upload(api, client, body=None, *, apply=False, fy=2025, name="items.xml"):
    data = {"file": SimpleUploadedFile(name, body or xml(MUSTARD, '<STOCKITEM NAME="Rice"><BASEUNITS>Kg</BASEUNITS></STOCKITEM>')), "financial_year": str(fy), "apply": "true" if apply else "false"}
    return api.post(url(client), data, format="multipart")


def items(api, client):
    return {i["name"]: i for i in api.get(f"{base(client)}/stock-items/").json()["results"]}


def test_a_preview_says_what_would_happen_and_writes_nothing(api, client_record):
    done = upload(api, client_record)
    assert done.status_code == 200, done.content
    body = done.json()
    assert body["applied"] is False
    assert [(r["name"], r["item"], r["opening"]) for r in body["rows"]] == [("Mustard Oil 1L", "new", "add"), ("Rice", "new", "none")]
    assert [r["opening_qty"] for r in body["rows"]] == ["40", "0"], "a plain number, never 4E+1"
    assert items(api, client_record) == {}
    assert api.get(f"{base(client_record)}/stock-entries/").json()["results"] == []


def test_applying_makes_the_items_and_their_opening_stock(api, client_record):
    body = upload(api, client_record, apply=True).json()
    assert body["applied"] is True and body["counts"] == {"new": 2, "filled": 0, "same": 0, "opening_added": 1, "opening_skipped": 0}
    mustard = items(api, client_record)["Mustard Oil 1L"]
    assert (mustard["unit"], mustard["hsn_sac"], mustard["gst_rate"]) == ("Nos", "1514", "5.00")
    (entry,) = api.get(f"{base(client_record)}/stock-entries/").json()["results"]
    assert (entry["kind"], entry["entry_date"], entry["quantity"], entry["value_paise"], entry["name"]) == ("OPENING", "2025-04-01", "40.000", 4_000_00, "Mustard Oil 1L")
    report = api.get(f"{base(client_record)}/reports/inventory/", {"fy": 2025}).json()
    assert report["items"][0]["closing_qty"] == "40"


def test_applying_twice_changes_nothing_the_second_time(api, client_record):
    upload(api, client_record, apply=True)
    again = upload(api, client_record, apply=True).json()
    assert again["counts"] == {"new": 0, "filled": 0, "same": 2, "opening_added": 0, "opening_skipped": 1}
    assert [r["opening"] for r in again["rows"]] == ["exists", "none"]
    assert len(api.get(f"{base(client_record)}/stock-entries/").json()["results"]) == 1


def test_an_item_already_kept_is_only_filled_in_where_it_was_blank(api, client_record):
    api.post(f"{base(client_record)}/stock-items/", {"name": "mustard oil 1l", "unit": "Ltr"}, format="json")
    body = upload(api, client_record, apply=True).json()
    assert [(r["item"]) for r in body["rows"]][0] == "fill"
    kept = items(api, client_record)["mustard oil 1l"]
    assert kept["unit"] == "Ltr", "what a person typed is not overwritten"
    assert kept["hsn_sac"] == "1514" and kept["gst_rate"] == "5.00", "the blanks are filled"
    assert "Mustard Oil 1L" not in items(api, client_record)


def test_opening_stock_is_not_written_into_sealed_books_and_the_row_says_why(api, firm, client_record):
    from core.db.session import firm_context

    client_record.signed_off_through = datetime.date(2025, 6, 30)
    with firm_context(firm.pk):
        client_record.save(update_fields=["signed_off_through"])
    body = upload(api, client_record, apply=True).json()
    mustard = body["rows"][0]
    assert mustard["opening"] == "sealed" and "sealed" in mustard["reason"]
    assert body["counts"]["opening_skipped"] == 1
    assert "Mustard Oil 1L" in items(api, client_record), "the item itself is still made"


def test_a_file_that_is_not_a_stock_item_export_is_refused_in_words(api, client_record):
    refused = upload(api, client_record, body=b"not a file")
    assert refused.status_code == 422 and refused.json()["code"] == "tally_file_unreadable"


def test_only_someone_who_may_import_can_use_it(firm, client_record):
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert upload(reader, client_record).status_code == 403
