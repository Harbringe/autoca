"""Removing a bank account opened by mistake, and merging a duplicate into the account it should be. Real PostgreSQL."""

from __future__ import annotations

import datetime

import pytest

from banking.accounts import AccountChangeError, merge_account, remove_account
from banking.ingest import ingest_statement
from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import contra_ledger_for
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.models import MasterChange
from ledger.tests.support import make_ledger, post

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

#: The fixture statement: account 900000000000001, from 01-04-2025, 54 rows.
AXIS = b"%PDF-1.4 axis"


@pytest.fixture
def client():
    return create_client(create_firm("Account Tidy Firm"), "Sample Traders", datetime.date(2025, 4, 1))


def _account(client, number, ledger, *, code="TEST", kind="BANK"):
    account = BankAccount(firm_id=client.firm_id, client=client, bank_code=code, ledger_name=ledger, kind=kind)
    account.set_account_number(number)
    account.save()
    contra_ledger_for(account)
    return account


def test_an_empty_account_is_removed_with_its_ledger_and_the_removal_is_logged(client):
    with firm_context(client.firm_id):
        stray = _account(client, "XXXX9999", "Stray Bank A/c 9999")
        result = remove_account(stray, actor=None)
        assert result["ledger_removed"] is True
        assert not BankAccount.objects.filter(pk=stray.pk).exists()
        assert not LedgerAccount.objects.filter(client=client, name="Stray Bank A/c 9999").exists()
        assert MasterChange.objects.filter(client=client, action="REMOVED", label__contains="Stray Bank A/c 9999").exists()


def test_an_account_with_a_statement_is_not_removed(client):
    with firm_context(client.firm_id):
        account = ingest_statement(client=client, data=AXIS).bank_account
        with pytest.raises(AccountChangeError, match="statement"):
            remove_account(account, actor=None)
        assert BankAccount.objects.filter(pk=account.pk).exists()


def test_an_account_with_posted_entries_is_not_removed(client):
    with firm_context(client.firm_id):
        account = _account(client, "XXXX8888", "Posted Bank A/c 8888")
        post(client, datetime.date(2025, 5, 1), contra_ledger_for(account), make_ledger(client, "Rent", LedgerGroup.INDIRECT_EXPENSE), 100_00)
        with pytest.raises(AccountChangeError, match="posted"):
            remove_account(account, actor=None)


def test_a_duplicate_is_merged_and_its_rows_are_fingerprinted_for_the_right_account(client):
    with firm_context(client.firm_id):
        duplicate = ingest_statement(client=client, data=AXIS).bank_account
        right = _account(client, "123400000000001", "Right Bank A/c 0001", code="AXIS")
        rows = StatementTransaction.objects.filter(bank_account=duplicate).count()

        result = merge_account(duplicate, right, actor=None)

        assert result["statements"] == 1 and result["rows"] == rows
        assert not BankAccount.objects.filter(pk=duplicate.pk).exists()
        assert Statement.objects.filter(bank_account=right).count() == 1
        moved = StatementTransaction.objects.filter(bank_account=right).order_by("row_number")
        assert moved.count() == rows
        first = moved.first()
        assert first.dedupe_hash == StatementTransaction.compute_dedupe_hash(
            account_hash=right.account_number_hash, value_date=first.value_date, narration=first.narration,
            debit_paise=first.debit_paise, credit_paise=first.credit_paise, balance_paise=first.balance_paise,
        )


def test_a_merge_is_refused_while_anything_is_posted_to_the_duplicate(client):
    with firm_context(client.firm_id):
        duplicate = _account(client, "XXXX7777", "Dup Bank A/c 7777")
        right = _account(client, "123400007777", "Right Bank A/c 7777")
        post(client, datetime.date(2025, 5, 1), contra_ledger_for(duplicate), make_ledger(client, "Rent", LedgerGroup.INDIRECT_EXPENSE), 50_00)
        with pytest.raises(AccountChangeError, match="never moved"):
            merge_account(duplicate, right, actor=None)
        assert BankAccount.objects.filter(pk=duplicate.pk).exists()


def test_a_merge_is_refused_when_both_have_statements_for_the_same_days(client):
    with firm_context(client.firm_id):
        right = ingest_statement(client=client, data=AXIS).bank_account
        duplicate = _account(client, "XXXX6666", "Dup Bank A/c 6666", code="AXIS")
        statement = Statement.objects.get(bank_account=right)
        statement.bank_account = duplicate
        statement.save(update_fields=["bank_account"])
        StatementTransaction.objects.filter(statement=statement).update(bank_account=duplicate)
        # Now the duplicate holds a statement; give the right account another for the same days by moving a copy back is not
        # possible without a second file, so check the overlap rule against a statement on each side.
        other = Statement.objects.create(
            firm_id=client.firm_id, bank_account=right, document=statement.document.__class__.objects.create(
                firm_id=client.firm_id, client=client, kind=statement.document.kind, sha256="0" * 64
            ),
            period_start=statement.period_start, period_end=statement.period_end, opening_balance_paise=0, closing_balance_paise=0,
            total_debit_paise=0, total_credit_paise=0,
        )
        assert other.pk
        with pytest.raises(AccountChangeError, match="covers days"):
            merge_account(duplicate, right, actor=None)


def test_accounts_of_different_kinds_are_not_merged(client):
    with firm_context(client.firm_id):
        bank = _account(client, "XXXX5555", "Bank A/c 5555")
        loan = _account(client, "XXXX4444", "Loan A/c 4444", kind="LOAN")
        with pytest.raises(AccountChangeError, match="cannot be one account"):
            merge_account(bank, loan, actor=None)


def test_different_confirmed_openings_are_not_merged(client):
    with firm_context(client.firm_id):
        a = _account(client, "XXXX3333", "A Bank A/c 3333")
        b = _account(client, "XXXX2222", "B Bank A/c 2222")
        for account, paise in ((a, 1_000_00), (b, 2_000_00)):
            account.opening_balance_paise, account.opening_as_of = paise, datetime.date(2025, 3, 31)
            account.save(update_fields=["opening_balance_paise", "opening_as_of"])
        with pytest.raises(AccountChangeError, match="opening"):
            merge_account(a, b, actor=None)
