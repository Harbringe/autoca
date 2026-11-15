"""A payment already on a supplier's own ledger is not narrated "paid to X towards X"."""

from types import SimpleNamespace

from ledger.approval import book_narration_for


def row(*, debit, party_account):
    ledger = SimpleNamespace(name="Sample Traders", is_bank_or_cash=False, is_party_account=party_account)
    txn = SimpleNamespace(
        amount_paise=37_800_00, is_debit=debit, narration="NEFT-X1-SAMPLE TRADERS", bank_account=SimpleNamespace(kind="BANK")
    )
    return SimpleNamespace(book_narration="", ledger=ledger, transaction=txn, counterparty="SAMPLE TRADERS", channel="NEFT")


def test_a_party_accounts_payment_names_the_party_once():
    text = book_narration_for(row(debit=True, party_account=True))
    assert text.startswith("Being ₹37,800.00 paid to Sample Traders by NEFT")
    assert "towards" not in text


def test_a_party_accounts_receipt_names_the_party_once():
    assert book_narration_for(row(debit=False, party_account=True)).startswith("Being ₹37,800.00 received from Sample Traders by NEFT")


def test_an_ordinary_ledger_still_reads_towards_the_ledger():
    assert "paid to SAMPLE TRADERS towards Sample Traders" in book_narration_for(row(debit=True, party_account=False))
