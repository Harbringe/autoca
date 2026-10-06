"""A person can see how a statement's table was read, and name the columns when the reader could not."""

from __future__ import annotations

import io
import json

import pytest

from api.tests.test_bills import base
from banking.tests.layouts import document
from integrations.pdf.base import PdfTextAdapter
from integrations.registry import reset_adapter_cache

pytestmark = pytest.mark.django_db

HEADER = ["Date", "Details", "Out", "In", "Running"]
ROWS = [
    ["01-04-2025", "OPENING CREDIT", "", "1000.00", "1000.00"],
    ["02-04-2025", "RENT", "200.00", "", "800.00"],
    ["03-04-2025", "SALARY", "", "50.00", "850.00"],
    ["04-04-2025", "SHOP", "100.00", "", "750.00"],
]


class TableAdapter(PdfTextAdapter):
    """Hands back a fixed table whatever bytes arrive."""

    table = [HEADER, *ROWS]

    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes):
        return document("Account statement\nAccount number: 1000000000099\nIFSC: TEST0000001", TableAdapter.table)


@pytest.fixture(autouse=True)
def table_pdfs(tmp_path, settings):
    TableAdapter.table = [HEADER, *ROWS]
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": f"{__name__}.TableAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "pdf": {}, "storage": {"root": str(tmp_path / "s")}}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def pdf():
    f = io.BytesIO(b"%PDF-1.4 layout test")
    f.name = "s.pdf"
    return f


def test_the_preview_shows_the_first_rows_and_the_columns_it_proved(api, client_record):
    response = api.post(f"{base(client_record)}/statements/preview/", {"file": pdf()}, format="multipart")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["header"][:2] == ["Date", "Details"] and body["width"] == 5 and body["total_rows"] == 4
    assert body["rows"][0][1] == "OPENING CREDIT"
    assert body["proposed"]["date"] == 0 and body["proposed"]["balance"] == 4 and body["error"] == ""


def test_the_preview_says_why_it_stopped_when_the_balances_do_not_follow(api, client_record):
    TableAdapter.table = [HEADER, *ROWS[:2], ["04-04-2025", "SHOP", "100.00", "", "500.00"], ROWS[2]]

    body = api.post(f"{base(client_record)}/statements/preview/", {"file": pdf()}, format="multipart").json()

    assert body["proposed"] == {} and "breaks at transaction 3" in body["error"]
    assert len(body["rows"]) == 4  # the person still sees the table


def test_the_columns_a_person_names_are_used_and_proved(api, client_record):
    layout = {"date": 0, "narration": 1, "debit": 2, "credit": 3, "balance": 4}

    ok = api.post(f"{base(client_record)}/statements/upload/", {"file": pdf(), "layout": json.dumps(layout)}, format="multipart")

    assert ok.status_code in (200, 202), ok.content
    assert ok.json()["status"] == "SUCCEEDED", ok.json()


def test_a_wrong_choice_is_refused_by_the_arithmetic_and_says_so(api, client_record):
    swapped = {"date": 0, "narration": 1, "debit": 3, "credit": 2, "balance": 4}

    response = api.post(f"{base(client_record)}/statements/upload/", {"file": pdf(), "layout": json.dumps(swapped)}, format="multipart")

    assert response.json()["status"] == "FAILED"
    assert "do not reproduce the statement's own balances" in response.json()["error"]


@pytest.mark.parametrize(
    "layout", ["not json", json.dumps([1, 2]), json.dumps({"colour": 1}), json.dumps({"date": -1}), json.dumps({"date": "0"})]
)
def test_a_malformed_layout_is_a_400(api, client_record, layout):
    response = api.post(f"{base(client_record)}/statements/upload/", {"file": pdf(), "layout": layout}, format="multipart")

    assert response.status_code == 400 and "layout" in response.json()["fields"]
