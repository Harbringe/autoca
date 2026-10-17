"""Staging and applying a Tally vouchers import: posting, idempotence, locks, refusals, undo, isolation."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied

from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.models import Client, FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from ledger import tally_voucher_import as tvi
from ledger.billing import allocate
from ledger.editing import EntryLockedError
from ledger.models import Bill, ImportKind, JournalEntry, LedgerImportRun, TallyVoucher
from ledger.tally_import import TallyImportError, TallyRunStaleError
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
    assert "Ghost" in reasons["g2"] and "later release" in reasons["g3"]
    posting = next(r for r in run.rows if r["guid"] == "g1")
    assert posting["lines"] and posting["figures"]["total_paise"] == 118000
    assert JournalEntry.objects.filter(client=client).count() == 0


def test_the_same_file_is_the_same_preview(firm, client, senior, chart):
    first, _ = stage(client, senior, [sale()])
    second, reused = stage(client, senior, [sale()])
    assert reused is True and second.pk == first.pk


def test_a_range_with_postings_is_refused(firm, client, senior, chart):
    post(client, datetime.date(2025, 4, 5), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    with pytest.raises(TallyImportError):
        stage(client, senior, [sale(date="20250401"), sale("g9", "9", "20250410")])


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


def test_another_firm_cannot_see_the_run(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    other = create_firm("Other Firm")
    with firm_context(other.pk):
        assert LedgerImportRun.objects.filter(pk=run.pk).count() == 0


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
    allocate(pay.lines.get(ledger_account=bill.party.ledger), amount_paise=118000, bill=bill)
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client, voucher_type="Sales").count() == 1


def test_undo_of_an_unconfirmed_run_is_refused(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)
