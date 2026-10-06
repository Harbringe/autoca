"""A credit-card statement goes in as a liability account, and its rows post against the card's own ledger."""

from __future__ import annotations

import io

import pytest

from api.tests.test_bills import base, make_ledger
from banking.tests.test_card_parser import SINGLE, SUMMARY, TEXT, doc
from classify.engine import review_queue
from integrations.pdf.base import PdfTextAdapter
from integrations.registry import reset_adapter_cache

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


class CardAdapter(PdfTextAdapter):
    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes):
        return doc(SUMMARY, SINGLE, text=TEXT)


@pytest.fixture(autouse=True)
def card_pdfs(tmp_path, settings):
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": f"{__name__}.CardAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {**settings.INTEGRATION_OPTIONS, "pdf": {}, "storage": {"root": str(tmp_path / "s")}}
    reset_adapter_cache()
    yield
    reset_adapter_cache()


def upload(api, client_record):
    file = io.BytesIO(b"%PDF-1.4 card")
    file.name = "card.pdf"
    return api.post(f"{base(client_record)}/statements/upload/", {"file": file}, format="multipart")


def test_a_card_statement_is_imported_as_a_credit_card_account(api, client_record):
    response = upload(api, client_record)

    assert response.status_code in (200, 202), response.content
    assert response.json()["status"] == "SUCCEEDED", response.json()
    accounts = api.get(f"{base(client_record)}/bank-accounts/").json()["results"]
    (account,) = accounts
    assert account["kind"] == "CARD" and account["account_last4"] == "1234"


def test_a_purchase_posts_as_a_journal_and_a_payment_from_the_bank_as_a_payment(api, client_record):
    from core.db.session import firm_context
    from ledger.models import JournalEntry

    upload(api, client_record)
    food = make_ledger(api, client_record, "Staff Welfare", "INDIRECT_EXPENSE")
    bank = make_ledger(api, client_record, "ICICI Bank A/c 9999", "BANK")
    with firm_context(client_record.firm_id):
        rows = {r.transaction.narration: r for r in review_queue(client_record)}
    for narration, ledger in (("SWIGGY BENGALURU", food), ("PAYMENT RECEIVED - THANK YOU", bank)):
        row = next(r for n, r in rows.items() if narration in n)
        placed = api.post(f"{V1}/classifications/{row.pk}/review/", {"ledger": ledger["id"], "learn": False}, format="json")
        assert placed.status_code == 200, placed.content
        posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
        assert posted.status_code == 201, posted.content

    with firm_context(client_record.firm_id):
        types = {e.source_transaction.narration[:8]: e.voucher_type for e in JournalEntry.objects.filter(client=client_record).select_related("source_transaction")}
    assert types == {"SWIGGY B": "Journal", "PAYMENT ": "Payment"}
    with firm_context(client_record.firm_id):
        from classify.models import LedgerAccount

        card = LedgerAccount.objects.get(client=client_record, name__contains="Credit Card")
    assert card.group == "CURRENT_LIABILITY"
