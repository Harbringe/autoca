"""Staging and applying a Tally vouchers import: posting, idempotence, locks, refusals, undo, isolation."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied

from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import ClassificationRule, Party, TransactionClassification
from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.models import Client, FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from documents.models import Document
from ledger import tally_voucher_import as tvi
from ledger.billing import allocate, open_amount
from ledger.editing import EntryLockedError
from ledger.models import Bill, BillAllocation, ImportKind, JournalEntry, TallyVoucher
from ledger.tally_import import TallyImportError, TallyOverlapError, TallyRunStaleError
from ledger.tally_parse import TallyParseError
from ledger.tally_voucher_import import confirm_vouchers, stage_vouchers, undo_run
from ledger.tests.support import make_ledger, post
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml

pytestmark = pytest.mark.django_db

FY = 2025
START = datetime.date(2025, 4, 1)


def member(firm, role, email):
    user = User.objects.create_user(email=email, password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def firm():
    return create_firm("Voucher Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Voucher Client", START)


@pytest.fixture
def senior(firm, client):
    membership = member(firm, Role.SENIOR_CA, "lead@example.test")
    with firm_context(firm.pk):
        Client.objects.filter(pk=client.pk).update(lead=membership)
    client.lead = membership
    return membership


@pytest.fixture
def chart(firm, client):
    with firm_context(firm.pk):
        for name, group in [
            ("Acme Traders", G.DEBTOR), ("Sales", G.SALES), ("Output CGST", G.DUTIES_AND_TAXES),
            ("Output SGST", G.DUTIES_AND_TAXES), ("Cash", G.CASH), ("Rent", G.INDIRECT_EXPENSE), ("Bank One", G.BANK),
        ]:
            make_ledger(client, name, group)
        yield


def sale(guid="g1", number="1", date="20250401"):
    return voucher(
        guid=guid, vtype="Sales", number=number, date=date, party="Acme Traders",
        lines=[line("Acme Traders", 1180.0, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )


def stage(client, senior, vouchers, **kw):
    return stage_vouchers(client, senior, senior.user, data=vouchers_xml(vouchers), filename="v.xml", **kw)


def test_the_link_table_is_one_row_per_guid_per_client():
    assert ImportKind.VOUCHERS == "VOUCHERS"
    assert "uniq_tally_guid_per_client" in {c.name for c in TallyVoucher._meta.constraints}


def test_preview_counts_and_writes_only_the_run(firm, client, senior, chart):
    bad = voucher(guid="g2", vtype="Journal", number="2", date="20250402", lines=[line("Rent", 10.0), line("Ghost", -10.0)])
    bank = voucher(guid="g3", vtype="Payment", number="3", date="20250403", lines=[line("Rent", 10.0), line("Bank One", -10.0)])
    run, reused = stage(client, senior, [sale(), bad, bank])
    assert reused is False
    assert run.kind == "VOUCHERS" and run.status == "PREVIEW" and run.financial_year == FY
    assert run.counts["vouchers"] == 3 and run.counts["will_post"] == 1 and run.counts["will_make_bill"] == 1
    assert run.counts["skipped"] == 2 and run.counts["bank_waiting"] == 1
    reasons = {r["guid"]: r["reason"] for r in run.rows if r["action"] == "skip"}
    assert "Ghost" in reasons["g2"] and "bank account" in reasons["g3"]
    posting = next(r for r in run.rows if r["guid"] == "g1")
    assert posting["lines"] and posting["figures"]["total_paise"] == 118000
    assert JournalEntry.objects.filter(client=client).count() == 0


def test_the_same_file_is_the_same_preview(firm, client, senior, chart):
    first, _ = stage(client, senior, [sale()])
    second, reused = stage(client, senior, [sale()])
    assert reused is True and second.pk == first.pk


def test_a_range_with_postings_is_a_warning_the_accountant_decides(firm, client, senior, chart):
    post(client, datetime.date(2025, 4, 5), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    run, _ = stage(client, senior, [sale(date="20250401"), sale("g9", "9", "20250410")])
    assert run.counts["existing_entries"] == 1
    with pytest.raises(TallyOverlapError):
        confirm_vouchers(run, senior, senior.user)
    assert confirm_vouchers(run, senior, senior.user, allow_overlap=True).result["posted"] == 2


def test_two_companies_are_refused(firm, client, senior, chart):
    data = vouchers_xml([sale()], company="ONE").replace(
        b"</STATICVARIABLES>", b"<SVCURRENTCOMPANY>TWO</SVCURRENTCOMPANY></STATICVARIABLES>"
    )
    with pytest.raises(TallyImportError):
        stage_vouchers(client, senior, senior.user, data=data, filename="v.xml")


def test_a_signed_off_period_is_refused(firm, client, senior, chart, monkeypatch):
    monkeypatch.setattr("ledger.editing.locked_through", lambda client_id: datetime.date(2025, 4, 30))
    with pytest.raises(EntryLockedError):
        stage(client, senior, [sale()])


def test_a_file_that_is_not_vouchers_is_a_parse_error(firm, client, senior, chart):
    with pytest.raises(TallyParseError):
        stage_vouchers(client, senior, senior.user, data=b"<ENVELOPE><X/></ENVELOPE>", filename="v.xml")


def test_only_the_leads_and_admins_may_stage(firm, client, chart):
    other = member(firm, Role.STAFF, "other@example.test")
    with pytest.raises(PermissionDenied):
        stage_vouchers(client, other, other.user, data=vouchers_xml([sale()]), filename="v.xml")


# ---------------------------------------------------------------------------
# Confirming
# ---------------------------------------------------------------------------


def test_confirm_posts_exactly_the_tally_lines_and_makes_the_bill(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    done = confirm_vouchers(run, senior, senior.user)
    assert done.status == "CONFIRMED" and done.result["posted"] == 1 and done.result["bills"] == 1
    entry = JournalEntry.objects.get(client=client)
    assert entry.voucher_type == "Sales" and entry.entry_kind == "VOUCHER"
    got = sorted((ln.ledger_account.name, ln.signed_paise) for ln in entry.lines.select_related("ledger_account"))
    assert got == sorted([("Acme Traders", 118000), ("Sales", -100000), ("Output CGST", -9000), ("Output SGST", -9000)])
    bill = Bill.objects.get(client=client)
    assert (bill.kind, bill.reference, bill.taxable_paise, bill.cgst_paise, bill.total_paise, bill.entry_id) == (
        "SALES", "1", 100000, 9000, 118000, entry.pk,
    )
    assert bill.party.canonical_name == "Acme Traders" and bill.party.ledger.name == "Acme Traders"
    assert TallyVoucher.objects.get(client=client).guid == "g1"


def test_a_second_confirm_posts_nothing_more(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    again = confirm_vouchers(run, senior, senior.user)
    assert again.status == "CONFIRMED" and JournalEntry.objects.filter(client=client).count() == 1


def test_a_cash_sale_posts_with_no_bill_and_no_party(firm, client, senior, chart):
    v = voucher(
        guid="c1", vtype="Sales", number="5", date="20250402", party="Cash",
        lines=[line("Cash", 500.0, party=True), line("Sales", -500.0)],
    )
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 1 and Bill.objects.filter(client=client).count() == 0


def test_a_journal_posts_as_a_journal_entry(firm, client, senior, chart):
    v = voucher(
        guid="j1", vtype="Journal", number="7", date="20250403",
        lines=[line("Rent", 100.0), line("Cash", -100.0)], narration="Rent for April",
    )
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    e = JournalEntry.objects.get(client=client)
    assert (e.entry_kind, e.voucher_type, e.narration) == ("JOURNAL", "Journal", "Rent for April")


def test_the_same_tally_number_in_two_types_does_not_collide(firm, client, senior, chart):
    j = voucher(guid="j1", vtype="Journal", number="1", date="20250403", lines=[line("Rent", 100.0), line("Cash", -100.0)])
    run, _ = stage(client, senior, [sale(number="1"), j])
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 2


def test_a_duplicate_invoice_number_posts_the_entry_without_a_second_bill(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale("g1", "1"), sale("g2", "1", "20250402")])
    done = confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 2 and Bill.objects.filter(client=client).count() == 1
    assert any("duplicate" in f["reason"].lower() for f in done.result["failed"])


def test_a_changed_chart_makes_the_preview_stale(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    make_ledger(client, "A new ledger", G.INDIRECT_EXPENSE)
    with pytest.raises(TallyRunStaleError):
        confirm_vouchers(run, senior, senior.user)


def test_a_signed_off_date_is_not_posted(firm, client, senior, chart, monkeypatch):
    run, _ = stage(client, senior, [sale()])
    monkeypatch.setattr("ledger.editing.locked_through", lambda client_id: datetime.date(2025, 4, 30))
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 0 and done.result["failed"]
    assert JournalEntry.objects.filter(client=client).count() == 0


def test_one_bad_voucher_does_not_stop_the_rest(firm, client, senior, chart, monkeypatch):
    run, _ = stage(client, senior, [sale("g1", "1"), sale("g2", "2", "20250402")])
    real = tvi._bill

    def flaky(client_, party, entry, row, f, date, year):
        if row["guid"] == "g1":
            raise RuntimeError("boom")
        return real(client_, party, entry, row, f, date, year)

    monkeypatch.setattr(tvi, "_bill", flaky)
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 1 and [f["guid"] for f in done.result["failed"]] == ["g1"]
    assert JournalEntry.objects.filter(client=client).count() == 1  # g1 rolled back entirely


# ---------------------------------------------------------------------------
# Undoing
# ---------------------------------------------------------------------------


def test_undo_removes_everything_the_run_wrote(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    undone = undo_run(run, senior, senior.user)
    assert undone.status == "DISCARDED" and undone.result["undone"] == 1
    assert JournalEntry.objects.filter(client=client).count() == 0
    assert Bill.objects.filter(client=client).count() == 0 and TallyVoucher.objects.filter(client=client).count() == 0


def test_after_undo_the_same_file_can_be_imported_again(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    undo_run(run, senior, senior.user)
    run2, _ = stage(client, senior, [sale()])
    assert confirm_vouchers(run2, senior, senior.user).result["posted"] == 1


def test_undo_is_refused_once_a_payment_is_applied(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    bill = Bill.objects.get(client=client)
    pay = post(client, datetime.date(2025, 4, 20), make_ledger(client, "Cash", G.CASH), bill.party.ledger, 118000)
    party_line = pay.lines.get(ledger_account=bill.party.ledger)
    party_line.party = bill.party
    party_line.save(update_fields=["party"])
    allocate(party_line, amount_paise=118000, bill=bill)
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client, voucher_type="Sales").count() == 1


def test_undo_of_an_unconfirmed_run_is_refused(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)


# ---------------------------------------------------------------------------
# Bank vouchers: statement rows, placements, and the bills a payment settles
# ---------------------------------------------------------------------------


@pytest.fixture
def banks(firm, client, chart):
    """Two bank accounts whose ledgers carry the accounts' names, the first with an opening balance."""
    made = {}
    for name, opening in (("Bank One", 500000), ("Bank Two", None)):
        account = BankAccount(firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name=name)
        account.set_account_number("5010000000" + str(len(made)))
        if opening is not None:
            account.opening_balance_paise, account.opening_as_of = opening, START
        account.save()
        make_ledger(client, name, G.BANK)
        made[name] = account
    return made


def payment(guid="p1", number="10", date="20250405", amount=10.0):
    return voucher(
        guid=guid, vtype="Payment", number=number, date=date, narration="Office rent",
        lines=[line("Rent", amount), line("Bank One", -amount)],
    )


def test_a_bank_payment_becomes_a_statement_row_a_placement_and_an_entry(firm, client, senior, banks):
    run, _ = stage(client, senior, [payment()])
    assert run.counts["bank_rows"] == 1
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 1 and done.result["bank_rows"] == 1
    txn = StatementTransaction.objects.get(bank_account=banks["Bank One"])
    assert (txn.debit_paise, txn.credit_paise, txn.narration) == (1000, 0, "Office rent")
    assert txn.balance_paise == 499000
    statement = txn.statement
    assert (statement.opening_balance_paise, statement.closing_balance_paise, statement.transaction_count) == (500000, 499000, 1)
    assert statement.document.kind == "TALLY_EXPORT"
    placement = TransactionClassification.objects.get(transaction=txn)
    assert (placement.ledger.name, placement.method, placement.needs_review) == ("Rent", "REVIEWED", False)
    entry = JournalEntry.objects.get(client=client)
    assert (entry.entry_kind, entry.voucher_type, entry.source_transaction_id) == ("BANK", "Payment", txn.pk)
    assert sorted((ln.ledger_account.name, ln.signed_paise) for ln in entry.lines.select_related("ledger_account")) == [
        ("Bank One", -1000), ("Rent", 1000),
    ]


def test_a_receipt_settles_the_bill_tally_names(firm, client, senior, banks):
    receipt = voucher(
        guid="r1", vtype="Receipt", number="11", date="20250410", party="Acme Traders",
        lines=[line("Bank One", 1180.0), line("Acme Traders", -1180.0, party=True, bills=[("1", "Agst Ref", 1180.0)])],
    )
    run, _ = stage(client, senior, [sale(), receipt])
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 2 and done.result["unmatched_bills"] == 0
    bill = Bill.objects.get(client=client)
    assert open_amount(bill) == 0
    allocation = BillAllocation.objects.get(bill=bill)
    assert (allocation.kind, allocation.amount_paise) == ("AGAINST_BILL", 118000)
    txn = StatementTransaction.objects.get(bank_account=banks["Bank One"])
    assert (txn.credit_paise, txn.balance_paise) == (118000, 618000)


def test_a_receipt_naming_a_bill_that_is_not_here_is_left_on_account(firm, client, senior, banks):
    receipt = voucher(
        guid="r2", vtype="Receipt", number="12", date="20250410", party="Acme Traders",
        lines=[line("Bank One", 500.0), line("Acme Traders", -500.0, party=True, bills=[("OLD-9", "Agst Ref", 500.0)])],
    )
    run, _ = stage(client, senior, [receipt])
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["unmatched_bills"] == 1
    assert BillAllocation.objects.get(client=client).kind == "ON_ACCOUNT"


def test_a_contra_between_two_accounts_is_one_entry_with_a_row_on_each(firm, client, senior, banks):
    contra = voucher(
        guid="c1", vtype="Contra", number="3", date="20250406",
        lines=[line("Bank Two", 5000.0), line("Bank One", -5000.0)],
    )
    run, _ = stage(client, senior, [contra])
    assert run.counts["bank_rows"] == 2
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 1
    entry = JournalEntry.objects.get(client=client)
    out = TransactionClassification.objects.get(transaction__bank_account=banks["Bank One"])
    into = TransactionClassification.objects.get(transaction__bank_account=banks["Bank Two"])
    assert (out.ledger.name, into.ledger.name) == ("Bank Two", "Bank One")
    assert out.is_self_transfer and into.is_self_transfer
    # One of the two rows is the entry's own source and the other is its mirror; which is which does not matter.
    mirrored = [c for c in (out, into) if c.mirrored_entry_id]
    assert len(mirrored) == 1 and mirrored[0].mirrored_entry_id == entry.pk
    source = into if mirrored[0] is out else out
    assert entry.source_transaction_id == source.transaction_id


def test_undo_takes_the_statements_and_settlements_back_with_the_entries(firm, client, senior, banks):
    receipt = voucher(
        guid="r1", vtype="Receipt", number="11", date="20250410", party="Acme Traders",
        lines=[line("Bank One", 1180.0), line("Acme Traders", -1180.0, party=True, bills=[("1", "Agst Ref", 1180.0)])],
    )
    run, _ = stage(client, senior, [sale(), receipt, payment()])
    confirm_vouchers(run, senior, senior.user)
    undo_run(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 0
    assert Bill.objects.filter(client=client).count() == 0 and BillAllocation.objects.filter(client=client).count() == 0
    assert StatementTransaction.objects.filter(bank_account__client=client).count() == 0
    assert Statement.objects.filter(bank_account__client=client).count() == 0
    assert Document.objects.filter(client=client, kind="TALLY_EXPORT", storage_key="").count() == 0  # the file as uploaded is kept
    assert TransactionClassification.objects.filter(transaction__bank_account__client=client).count() == 0


def test_a_bank_ledger_with_no_account_is_left_out_and_counted(firm, client, senior, chart):
    make_ledger(client, "Bank Orphan", G.BANK)
    v = voucher(guid="o1", vtype="Payment", number="1", date="20250405", lines=[line("Rent", 10.0), line("Bank Orphan", -10.0)])
    run, _ = stage(client, senior, [v])
    assert run.counts["will_post"] == 0 and run.counts["bank_waiting"] == 1
    assert "bank account" in run.rows[0]["reason"]


# ---------------------------------------------------------------------------
# The period stays empty, real statements and Tally history never overlap, and the history teaches
# ---------------------------------------------------------------------------


def test_entries_posted_after_the_preview_need_the_accountants_say_so(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale(date="20250401")])
    post(client, datetime.date(2025, 4, 1), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    with pytest.raises(TallyOverlapError):
        confirm_vouchers(run, senior, senior.user)


def test_a_statement_for_dates_the_import_filled_is_refused(firm, client, senior, banks):
    from types import SimpleNamespace

    from banking.ingest import StatementOverlapsTallyError, _refuse_over_tally_history

    run, _ = stage(client, senior, [payment()])
    confirm_vouchers(run, senior, senior.user)
    account = banks["Bank One"]
    with pytest.raises(StatementOverlapsTallyError):
        _refuse_over_tally_history(account, SimpleNamespace(period_start=datetime.date(2025, 4, 1), period_end=datetime.date(2025, 4, 30)))
    # A statement that starts after the imported history is fine.
    _refuse_over_tally_history(account, SimpleNamespace(period_start=datetime.date(2025, 5, 1), period_end=datetime.date(2025, 5, 31)))


def test_an_imported_statement_cannot_be_removed_on_its_own(firm, client, senior, banks):
    from banking.removal import StatementRemovalError, remove_statement

    run, _ = stage(client, senior, [payment()])
    confirm_vouchers(run, senior, senior.user)
    statement = Statement.objects.get(bank_account=banks["Bank One"])
    with pytest.raises(StatementRemovalError):
        remove_statement(statement, actor=senior.user)


def test_a_creditor_ledger_becomes_a_party_even_without_a_bill(firm, client, senior, banks):
    make_ledger(client, "Zed Supplies", G.CREDITOR)
    v = voucher(
        guid="z1", vtype="Payment", number="20", date="20250405",
        lines=[line("Zed Supplies", 500.0, party=True), line("Bank One", -500.0)],
    )
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    party = Party.objects.get(client=client, canonical_name="Zed Supplies")
    assert party.role == "VENDOR" and party.ledger.name == "Zed Supplies"
    assert JournalEntry.objects.get(client=client).lines.get(ledger_account__name="Zed Supplies").party_id == party.pk
    assert TransactionClassification.objects.get(transaction__bank_account=banks["Bank One"]).party_id == party.pk


def neft(guid, date, payee, ledger, amount=100.0):
    return voucher(
        guid=guid, vtype="Payment", number=guid, date=date, narration=f"NEFT-HDFCN52025-{payee}-INV {guid}",
        lines=[line(ledger, amount), line("Bank One", -amount)],
    )


def test_a_payee_who_always_went_to_one_ledger_earns_a_rule_that_never_posts_alone(firm, client, senior, banks):
    make_ledger(client, "Repairs", G.INDIRECT_EXPENSE)
    history = [neft(f"a{i}", f"2025040{i}", "GANESH STEEL PVT LTD", "Rent") for i in range(1, 5)]
    run, _ = stage(client, senior, history)
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["rules_learned"] == 1
    rule = ClassificationRule.objects.get(client=client)
    assert (rule.pattern, rule.direction, rule.ledger.name, rule.source) == ("GANESHSTEELPVTLTD", "DEBIT", "Rent", "LEARNED")
    assert 0.75 <= rule.confidence <= 0.88


def test_a_payee_whose_payments_went_to_several_ledgers_earns_no_rule(firm, client, senior, banks):
    make_ledger(client, "Repairs", G.INDIRECT_EXPENSE)
    history = [
        neft("b1", "20250401", "PATEL AGENCY", "Rent"), neft("b2", "20250402", "PATEL AGENCY", "Rent"),
        neft("b3", "20250403", "PATEL AGENCY", "Repairs"), neft("b4", "20250404", "PATEL AGENCY", "Repairs"),
    ]
    run, _ = stage(client, senior, history)
    assert confirm_vouchers(run, senior, senior.user).result["rules_learned"] == 0
    assert ClassificationRule.objects.filter(client=client).count() == 0


def test_undo_takes_the_rules_it_learned_back_unless_they_were_used(firm, client, senior, banks):
    history = [neft(f"c{i}", f"2025040{i}", "GANESH STEEL PVT LTD", "Rent") for i in range(1, 4)]
    run, _ = stage(client, senior, history)
    confirm_vouchers(run, senior, senior.user)
    assert ClassificationRule.objects.filter(client=client).count() == 1
    undo_run(run, senior, senior.user)
    assert ClassificationRule.objects.filter(client=client).count() == 0


# ---------------------------------------------------------------------------
# Multi-line bank vouchers, loan accounts, tax at source on bills, and the stock register
# ---------------------------------------------------------------------------


def test_a_payment_with_tds_is_one_bank_row_and_keeps_every_line(firm, client, senior, banks):
    make_ledger(client, "Zed Supplies", G.CREDITOR)
    make_ledger(client, "TDS Payable", G.DUTIES_AND_TAXES)
    v = voucher(
        guid="t1", vtype="Payment", number="30", date="20250405", party="Zed Supplies",
        lines=[line("Zed Supplies", 100.0, party=True), line("TDS Payable", -2.0), line("Bank One", -98.0)],
    )
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    entry = JournalEntry.objects.get(client=client)
    assert entry.lines.count() == 3
    txn = StatementTransaction.objects.get(bank_account=banks["Bank One"])
    assert (txn.debit_paise, txn.credit_paise) == (9800, 0)
    placement = TransactionClassification.objects.get(transaction=txn)
    assert placement.ledger.name == "Zed Supplies" and placement.party.canonical_name == "Zed Supplies"
    # Editing it as a two-line bank row would drop the TDS line, so that is refused.
    from ledger.editing import WrongEntryKindError, require_standard_shape

    with pytest.raises(WrongEntryKindError):
        require_standard_shape(entry)


def test_a_loan_account_statement_counts_what_is_owed(firm, client, senior, chart):
    loan = BankAccount(firm_id=client.firm_id, client=client, bank_code="SBI", kind="LOAN", ledger_name="SBI Loan")
    loan.set_account_number("5259000000")
    loan.opening_balance_paise, loan.opening_as_of = 100000, START
    loan.save()
    make_ledger(client, "SBI Loan", G.LOAN)
    make_ledger(client, "Bank Interest", G.INDIRECT_EXPENSE)
    v = voucher(guid="l1", vtype="Journal", number="9", date="20250430", lines=[line("Bank Interest", 5.0), line("SBI Loan", -5.0)])
    v["vtype"] = "Payment"  # entered as a payment voucher in Tally
    run, _ = stage(client, senior, [v])
    assert run.counts["bank_rows"] == 1
    confirm_vouchers(run, senior, senior.user)
    txn = StatementTransaction.objects.get(bank_account=loan)
    assert (txn.debit_paise, txn.credit_paise, txn.balance_paise) == (500, 0, 100500)
    assert txn.statement.closing_balance_paise == 100500


def test_tds_and_tcs_on_a_purchase_are_kept_on_the_bill(firm, client, senior, chart):
    make_ledger(client, "Zed Supplies", G.CREDITOR)
    make_ledger(client, "Purchases", G.PURCHASE)
    make_ledger(client, "TDS Payable", G.DUTIES_AND_TAXES)
    v = voucher(
        guid="d1", vtype="Purchase", number="P1", date="20250402", party="Zed Supplies",
        lines=[line("Zed Supplies", -990.0, party=True), line("Purchases", 1000.0), line("TDS Payable", -10.0)],
    )
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    bill = Bill.objects.get(client=client)
    assert (bill.taxable_paise, bill.tds_paise, bill.total_paise) == (100000, 1000, 99000)


def item_purchase():
    return voucher(
        guid="s1", vtype="Purchase", number="P2", date="20250403", party="Zed Supplies",
        lines=[line("Zed Supplies", -1180.0, party=True), line("Input CGST", 90.0), line("Input SGST", 90.0)],
        items=[("Oil 1L", "Purchases", 600.0, "600 BOX"), ("Oil 15L", "Purchases", 400.0, "20 BOX")],
    )


@pytest.fixture
def suppliers(client, chart):
    make_ledger(client, "Zed Supplies", G.CREDITOR)
    make_ledger(client, "Purchases", G.PURCHASE)
    make_ledger(client, "Input CGST", G.DUTIES_AND_TAXES)
    make_ledger(client, "Input SGST", G.DUTIES_AND_TAXES)


def test_an_item_invoice_writes_its_stock_movements_and_the_report_counts_them(firm, client, senior, suppliers):
    from ledger.inventory import build
    from ledger.models import StockEntry

    run, _ = stage(client, senior, [item_purchase()])
    assert run.counts["stock_lines"] == 2
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["stock_entries"] == 2
    rows = {r.name: r for r in StockEntry.objects.filter(client=client)}
    assert (rows["Oil 1L"].kind, rows["Oil 1L"].direction, rows["Oil 1L"].unit, str(rows["Oil 1L"].quantity), rows["Oil 1L"].value_paise) == (
        "TALLY", "IN", "BOX", "600.000", 60000,
    )
    report = build(client, 2025)
    assert report.bills_left_out == 0
    assert {i.name: i.closing_qty for i in report.items} == {"Oil 1L": 600, "Oil 15L": 20}


def test_undo_takes_the_stock_movements_back(firm, client, senior, suppliers):
    from ledger.models import StockEntry

    run, _ = stage(client, senior, [item_purchase()])
    confirm_vouchers(run, senior, senior.user)
    undo_run(run, senior, senior.user)
    assert StockEntry.objects.filter(client=client).count() == 0


# ---------------------------------------------------------------------------
# Setting a client up from the files, and importing bank reports
# ---------------------------------------------------------------------------


def _setup_from(client, senior, files, bank_ledgers=None):
    from ledger.tally_setup import apply_setup, discover_files

    found = discover_files(client, senior, files, bank_ledgers)
    done = apply_setup(
        client, senior, senior.user,
        ledgers=[{"name": p["name"], "group": p["group"]} for p in found["ledgers"]],
        accounts=[{**a, "account_number": a["account_number"] or "9999000011"} for a in found["accounts"]],
    )
    return found, done


@pytest.fixture
def in_context(firm, client):
    with firm_context(firm.pk):
        yield


def test_a_fresh_client_gets_its_ledgers_and_parties_from_a_vouchers_file(firm, client, senior, in_context):
    from classify.models import LedgerAccount

    files = [("vouchers.xml", vouchers_xml([sale()]))]
    found, done = _setup_from(client, senior, files)
    assert {p["name"]: p["group"] for p in found["ledgers"]} == {
        "Acme Traders": "DEBTOR", "Sales": "SALES", "Output CGST": "DUTIES_AND_TAXES", "Output SGST": "DUTIES_AND_TAXES",
    }
    assert done["ledgers"] == 4 and LedgerAccount.objects.filter(client=client, name="Output CGST").exists()
    run, _ = stage(client, senior, [sale()])
    confirmed = confirm_vouchers(run, senior, senior.user)
    assert confirmed.result["posted"] == 1 and confirmed.result["bills"] == 1
    assert Party.objects.get(client=client).canonical_name == "Acme Traders"


def test_setup_leaves_existing_ledgers_alone_and_waits_for_a_missing_account_number(firm, client, senior, in_context):
    from classify.models import LedgerAccount
    from ledger.tally_setup import apply_setup

    make_ledger(client, "Cash", G.CASH)
    done = apply_setup(
        client, senior, senior.user,
        ledgers=[{"name": "cash", "group": "SUSPENSE"}, {"name": "SBI SB A/C 62139251173", "group": "BANK"}],
        accounts=[{"ledger": "SBI SB A/C 62139251173", "kind": "BANK", "bank_code": "SBI", "account_number": ""}],
    )
    assert done["ledgers"] == 1 and done["accounts"] == 0 and done["waiting_for_a_number"] == ["SBI SB A/C 62139251173"]
    assert LedgerAccount.objects.get(client=client, name="Cash").group == "CASH"  # not regrouped by the file


def test_an_account_is_opened_tied_to_the_ledger_of_its_name(firm, client, senior, in_context):
    from ledger.tally_setup import apply_setup

    apply_setup(
        client, senior, senior.user,
        ledgers=[],
        accounts=[{"ledger": "SBI SB A/C 62139251173", "kind": "BANK", "bank_code": "sbi", "account_number": "62139251173"}],
    )
    account = BankAccount.objects.get(client=client)
    assert (account.ledger_name, account.bank_code, account.account_last4, account.kind) == ("SBI SB A/C 62139251173", "SBI", "1173", "BANK")


def _two_accounts(client, senior):
    from ledger.tally_setup import apply_setup

    apply_setup(
        client, senior, senior.user,
        ledgers=[{"name": n, "group": g} for n, g in (("Cash", "CASH"), ("Rent Paid", "INDIRECT_EXPENSE"), ("Bank Charges", "INDIRECT_EXPENSE"))],
        accounts=[
            {"ledger": "SBI SB A/C 62139251173", "kind": "BANK", "bank_code": "SBI", "account_number": "62139251173"},
            {"ledger": "SBI SB A/C 11112222333", "kind": "BANK", "bank_code": "SBI", "account_number": "11112222333"},
        ],
    )
    return {a.ledger_name: a for a in BankAccount.objects.filter(client=client)}


def test_a_bank_report_becomes_statement_rows_with_the_banks_own_narration(firm, client, senior, in_context):
    from ledger.tally_voucher_import import stage_bank_reports
    from ledger.tests.tally_voucher_xml import bank_report_xml, report_row

    accounts = _two_accounts(client, senior)
    data = bank_report_xml([
        report_row("4-Apr-25", "Cash", "Rcpt", debit=1501.0, number="1", narration="CASH DEPOSIT SELF"),
        report_row("5-Apr-25", "Rent Paid", "Pymt", credit=500.0, number="2", narration="NEFT RENT"),
        report_row("6-Apr-25", "(as per details)", "Pymt", credit=90.0, number="3"),
    ])
    account = accounts["SBI SB A/C 62139251173"]
    run, _ = stage_bank_reports(client, senior, senior.user, reports=[("sbi.xml", data, account.pk)])
    assert run.counts["will_post"] == 2 and run.counts["skipped"] == 1 and run.counts["bank_rows"] == 2
    assert any("several ledgers" in r["reason"] for r in run.rows if r["action"] == "skip")
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 2 and done.result["bank_rows"] == 2
    rows = list(StatementTransaction.objects.filter(bank_account=account).order_by("value_date"))
    assert [(t.narration, t.credit_paise, t.debit_paise, t.balance_paise) for t in rows] == [
        ("CASH DEPOSIT SELF", 150100, 0, 150100), ("NEFT RENT", 0, 50000, 100100),
    ]
    placed = {t.narration: TransactionClassification.objects.get(transaction=t).ledger.name for t in rows}
    assert placed == {"CASH DEPOSIT SELF": "Cash", "NEFT RENT": "Rent Paid"}


def test_a_transfer_in_two_banks_reports_is_written_once_with_a_row_on_each(firm, client, senior, in_context):
    from ledger.tally_voucher_import import stage_bank_reports
    from ledger.tests.tally_voucher_xml import bank_report_xml, report_row

    accounts = _two_accounts(client, senior)
    first, second = accounts["SBI SB A/C 62139251173"], accounts["SBI SB A/C 11112222333"]
    out = bank_report_xml([report_row("7-Apr-25", "SBI SB A/C 11112222333", "Pymt", credit=5000.0, number="9")])
    into = bank_report_xml([report_row("7-Apr-25", "SBI SB A/C 62139251173", "Pymt", debit=5000.0, number="9")])
    # The second report prints the same voucher from the other side (money in), so it carries the same identity.
    run, _ = stage_bank_reports(client, senior, senior.user, reports=[("a.xml", out, first.pk), ("b.xml", into, second.pk)])
    assert run.counts["will_post"] == 1 and run.counts["bank_rows"] == 2
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 1
    assert StatementTransaction.objects.filter(bank_account=first).count() == 1
    assert StatementTransaction.objects.filter(bank_account=second).count() == 1
    assert TransactionClassification.objects.filter(transaction__bank_account__client=client, is_self_transfer=True).count() == 2


def test_two_reports_for_one_account_are_refused(firm, client, senior, in_context):
    from ledger.tally_voucher_import import stage_bank_reports
    from ledger.tests.tally_voucher_xml import bank_report_xml, report_row

    account = _two_accounts(client, senior)["SBI SB A/C 62139251173"]
    data = bank_report_xml([report_row("4-Apr-25", "Cash", "Rcpt", debit=1.0)])
    with pytest.raises(TallyImportError):
        stage_bank_reports(client, senior, senior.user, reports=[("a.xml", data, account.pk), ("b.xml", data, account.pk)])
