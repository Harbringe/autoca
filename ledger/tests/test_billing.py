"""Party accounting against the real database: bills, party ledgers, settlement, and the guards underneath.

The arithmetic of where a rupee goes is proved separately and without a database in ``test_billing_plan``. What is
tested here is everything that needs one: that a voucher, a bill and its lines are written together, that a party gets
the right ledger, that settlements are tied to bills, and above all that the database itself refuses what the service
layer is meant to refuse -- so a bug in the service cannot corrupt the books.
"""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.db.models import ProtectedError, Sum
from django.utils import timezone

from classify.models import CRYPTO_PURPOSE, LedgerAccount, LedgerGroup, Party, PartyRole
from classify.seeds import seed_client
from core.crypto import blind_index
from core.db.session import firm_context
from core.fy import financial_year
from core.identity import invoice_key
from core.models import Client, Role
from documents.models import Document, DocumentKind
from ledger import approval, billing, editing
from ledger.billing import BillingError, BillInput
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    ChangeAction,
    Direction,
    EntryChange,
    EntryKind,
    JournalEntry,
    JournalLine,
    LedgerOpening,
    VoucherType,
)
from ledger.tests.test_approval import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    ledger,
    membership_for,
    senior,
)

pytestmark = pytest.mark.django_db

RAVI_GSTIN = "27AAACR5055K1Z7"
OWN_GSTIN = "27ABCDE1234F1Z5"
BILL_DATE = datetime.date(2025, 10, 1)
PAID_DATE = datetime.date(2025, 10, 20)


@pytest.fixture
def books(client):
    """The client, with the standard ledgers, inside its firm's context."""
    with firm_context(client.firm_id):
        seed_client(client)
        yield client


def make_party(client, name="Ravi Traders", role=PartyRole.VENDOR, gstin=RAVI_GSTIN):
    party = Party(firm_id=client.firm_id, client=client, canonical_name=name, role=role)
    if gstin:
        party.set_gstin(gstin)
    party.save()
    return party


def invoice(**overrides):
    fields = {"reference": "INV-1", "bill_date": BILL_DATE, "cgst": 900_000, "sgst": 900_000}
    fields.update(overrides)
    return BillInput(**fields)


def purchase(client, senior, party=None, *, heads=None, **overrides):
    party = party or make_party(client)
    heads = heads or [(purchases(client), 10_000_000)]
    return billing.post_purchase(client, party, heads, invoice(**overrides), membership=senior)


def purchases(client):
    return LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name="Purchases", defaults={"group": LedgerGroup.PURCHASE}
    )[0]


def bank(client):
    return LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name="Axis Bank A/c 9999", defaults={"group": LedgerGroup.BANK}
    )[0]


def payment_line(client, party, amount, on=PAID_DATE, *, direction=Direction.DEBIT):
    """A settling line on the party's own ledger, with the bank on the other side."""
    year = financial_year(on)
    voucher_type = VoucherType.PAYMENT if direction == Direction.DEBIT else VoucherType.RECEIPT
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=approval.allocate_voucher_number(client, year, voucher_type),
        financial_year=year,
        entry_date=on,
        voucher_type=voucher_type,
        narration="Settlement",
        approved_at=timezone.now(),
    )
    other = Direction.CREDIT if direction == Direction.DEBIT else Direction.DEBIT
    party_line = JournalLine.build(
        entry=entry, ledger_account=party.ledger, party=party, direction=direction, amount_paise=amount
    )
    bank_line = JournalLine.build(entry=entry, ledger_account=bank(client), direction=other, amount_paise=amount)
    JournalLine.objects.bulk_create([party_line, bank_line])
    return party_line


def lines_of(entry):
    return sorted(
        (line.ledger_account.name, line.direction, line.amount_paise)
        for line in entry.lines.select_related("ledger_account")
    )


def sign_off_through(client, date):
    Client.objects.filter(pk=client.pk).update(signed_off_through=date)


# ---------------------------------------------------------------------------
# Posting a purchase
# ---------------------------------------------------------------------------


def test_a_purchase_writes_the_voucher_the_bill_and_the_party_account_together(books, senior):
    bill = purchase(books, senior)
    party = bill.party
    party.refresh_from_db()

    assert bill.kind == BillKind.PURCHASE and bill.direction == Direction.CREDIT
    assert bill.total_paise == 11_800_000 and bill.taxable_paise == 10_000_000
    assert bill.entry.voucher_type == VoucherType.PURCHASE and bill.entry.entry_kind == EntryKind.VOUCHER
    assert bill.entry.source_transaction is None
    assert party.ledger.group == LedgerGroup.CREDITOR and party.ledger.name == "Ravi Traders"
    assert lines_of(bill.entry) == [
        ("Input CGST", Direction.DEBIT, 900_000),
        ("Input SGST", Direction.DEBIT, 900_000),
        ("Purchases", Direction.DEBIT, 10_000_000),
        ("Ravi Traders", Direction.CREDIT, 11_800_000),
    ]
    assert billing.open_amount(bill) == 11_800_000


def test_the_gst_lands_in_its_own_ledger_not_inside_the_purchase(books, senior):
    purchase(books, senior)

    def balance(name):
        ledger_ = LedgerAccount.objects.get(client=books, name=name)
        return JournalLine.objects.filter(ledger_account=ledger_).aggregate(t=Sum("signed_paise"))["t"]

    assert balance("Input CGST") == 900_000
    assert balance("Input SGST") == 900_000
    assert balance("Purchases") == 10_000_000


def test_only_the_party_line_names_the_party(books, senior):
    bill = purchase(books, senior)

    named = [line for line in bill.entry.lines.all() if line.party_id]
    assert [line.ledger_account.name for line in named] == ["Ravi Traders"]


def test_the_bill_carries_the_same_invoice_key_the_gst_module_uses(books, senior):
    bill = purchase(books, senior)

    assert bill.invoice_key == invoice_key(books.firm_id, RAVI_GSTIN, "INV-1")


def test_a_bill_records_which_of_the_clients_gstins_it_belongs_to(books, senior):
    bill = purchase(books, senior, own_gstin=OWN_GSTIN)

    assert bill.own_gstin_hash == blind_index(OWN_GSTIN, books.firm_id, CRYPTO_PURPOSE)


def test_the_same_invoice_cannot_be_booked_twice_however_the_number_is_typed(books, senior):
    party = make_party(books)
    purchase(books, senior, party, reference="INV-1")

    with pytest.raises(BillingError, match="already booked"):
        purchase(books, senior, party, reference="inv 001")
    assert Bill.objects.filter(party=party).count() == 1
    assert JournalEntry.objects.filter(voucher_type=VoucherType.PURCHASE).count() == 1


def test_another_supplier_may_use_the_same_invoice_number(books, senior):
    purchase(books, senior, make_party(books, "Ravi Traders", gstin=RAVI_GSTIN), reference="INV-1")
    other = purchase(books, senior, make_party(books, "Shah Stationers", gstin="24AAACS1234A1Z9"), reference="INV-1")

    assert other.pk and Bill.objects.count() == 2


def test_an_unregistered_supplier_is_identified_by_the_party_so_duplicates_are_still_caught(books, senior):
    party = make_party(books, "Local Kirana", gstin="")
    purchase(books, senior, party, reference="7", cgst=0, sgst=0)

    with pytest.raises(BillingError, match="already booked"):
        purchase(books, senior, party, reference="007", cgst=0, sgst=0)


def test_vouchers_are_numbered_in_their_own_series(books, senior):
    first = purchase(books, senior, reference="A-1")
    second = purchase(books, senior, first.party, reference="A-2")
    sale = billing.post_sales(
        books,
        make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin=""),
        [(LedgerAccount.objects.create(firm_id=books.firm_id, client=books, name="Sales", group=LedgerGroup.SALES), 5_000_000)],
        invoice(reference="S-1", cgst=0, sgst=0),
        membership=senior,
    )

    assert (first.entry.entry_no, second.entry.entry_no, sale.entry.entry_no) == (1, 2, 1)


# ---------------------------------------------------------------------------
# What the posting refuses
# ---------------------------------------------------------------------------


def test_a_customer_cannot_have_a_purchase(books, senior):
    customer = make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin="")

    with pytest.raises(BillingError, match="cannot have"):
        purchase(books, senior, customer)


def test_a_bank_or_party_ledger_is_not_a_head(books, senior):
    party = make_party(books)

    with pytest.raises(BillingError, match="bank, cash or party"):
        purchase(books, senior, party, heads=[(bank(books), 10_000_000)])


def test_a_proposed_ledger_cannot_carry_a_voucher_until_a_ca_accepts_it(books, senior):
    from classify.models import LedgerStatus

    proposed = ledger(books, "Hot Dog Stand")
    proposed.status = LedgerStatus.PROPOSED
    proposed.save(update_fields=["status"])

    with pytest.raises(BillingError, match="not in use"):
        purchase(books, senior, heads=[(proposed, 10_000_000)])


def test_read_only_members_cannot_book_vouchers(books, firm):
    read_only = membership_for(firm, Role.READ_ONLY)

    with pytest.raises(PermissionDenied):
        purchase(books, read_only)


def test_a_voucher_dated_inside_signed_off_books_is_refused_with_a_reason(books, senior):
    sign_off_through(books, datetime.date(2025, 10, 31))

    with pytest.raises(BillingError, match="signed off"):
        purchase(books, senior, bill_date=datetime.date(2025, 10, 15))


def test_the_database_itself_refuses_a_bill_dated_inside_signed_off_books(books, senior):
    bill = purchase(books, senior)
    sign_off_through(books, datetime.date(2025, 10, 31))

    with pytest.raises(DatabaseError, match="signed off"), transaction.atomic():
        Bill.objects.create(
            firm_id=books.firm_id, client=books, party=bill.party, kind=BillKind.PURCHASE, direction=Direction.CREDIT,
            reference="LATE", bill_date=datetime.date(2025, 10, 5), booked_on=datetime.date(2025, 10, 5),
            financial_year=2025, taxable_paise=100, total_paise=100, invoice_key="k" * 64,
        )


def test_a_failed_posting_leaves_nothing_behind(books, senior):
    party = make_party(books)
    with pytest.raises(BillingError):
        purchase(books, senior, party, tds=99_999_999)

    assert not Bill.objects.exists()
    assert not JournalEntry.objects.filter(voucher_type=VoucherType.PURCHASE).exists()


# ---------------------------------------------------------------------------
# Party ledgers
# ---------------------------------------------------------------------------


def test_a_ledger_the_client_already_has_for_the_party_is_adopted_not_duplicated(books, senior):
    """The Tally-import case: imported history and new vouchers share one account."""
    imported = ledger(books, "Ravi Traders", LedgerGroup.CREDITOR)

    bill = purchase(books, senior)
    bill.party.refresh_from_db()

    assert bill.party.ledger_id == imported.pk
    assert LedgerAccount.objects.filter(client=books, name="Ravi Traders").count() == 1


def test_a_name_taken_by_an_unrelated_ledger_is_told_apart_by_the_gstin(books, senior):
    ledger(books, "Ravi Traders", LedgerGroup.INDIRECT_EXPENSE)

    bill = purchase(books, senior)
    bill.party.refresh_from_db()

    assert bill.party.ledger.name == "Ravi Traders (K1Z7)"
    assert bill.party.ledger.group == LedgerGroup.CREDITOR


def test_a_customer_gets_a_debtor_ledger(books, senior):
    customer = make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin="")
    heads = [(LedgerAccount.objects.create(firm_id=books.firm_id, client=books, name="Sales", group=LedgerGroup.SALES), 5_000_000)]

    bill = billing.post_sales(books, customer, heads, invoice(reference="S-1", cgst=0, sgst=0), membership=senior)
    customer.refresh_from_db()

    assert customer.ledger.group == LedgerGroup.DEBTOR
    assert bill.direction == Direction.DEBIT
    assert lines_of(bill.entry) == [("Mehta Stores", Direction.DEBIT, 5_000_000), ("Sales", Direction.CREDIT, 5_000_000)]


def test_the_party_ledger_is_reused_on_the_next_voucher(books, senior):
    first = purchase(books, senior, reference="A-1")
    second = purchase(books, senior, first.party, reference="A-2")

    assert LedgerAccount.objects.filter(client=books, name="Ravi Traders").count() == 1
    assert first.party.ledger_id == second.party.ledger_id


# ---------------------------------------------------------------------------
# Reverse charge, TDS, notes
# ---------------------------------------------------------------------------


def test_a_reverse_charge_purchase_owes_the_supplier_only_the_taxable_value(books, senior):
    bill = purchase(books, senior, rcm=True)

    assert bill.total_paise == 10_000_000 and bill.rcm
    names = {name for name, _, _ in lines_of(bill.entry)}
    assert {"Input GST (RCM)", "GST Payable (RCM)"} <= names
    assert "Input CGST" not in names


def test_tds_is_booked_to_tds_payable_and_the_supplier_is_owed_the_net(books, senior):
    bill = purchase(books, senior, cgst=0, sgst=0, igst=900_000, tds=500_000, tds_section="194J")

    assert bill.total_paise == 10_400_000 and bill.tds_paise == 500_000
    tds_line = bill.entry.lines.get(ledger_account__name="TDS Payable")
    assert (tds_line.direction, tds_line.amount_paise, tds_line.tds_section) == (Direction.CREDIT, 500_000, "194J")


def test_a_debit_note_reverses_a_purchase_and_has_its_own_series(books, senior):
    bill = purchase(books, senior)
    note = billing.post_debit_note(
        books, bill.party, [(purchases(books), 1_000_000)], invoice(reference="DN-1", cgst=90_000, sgst=90_000),
        membership=senior,
    )

    assert note.kind == BillKind.DEBIT_NOTE and note.direction == Direction.DEBIT
    assert note.entry.voucher_type == VoucherType.DEBIT_NOTE and note.entry.entry_no == 1
    assert ("Ravi Traders", Direction.DEBIT, 1_180_000) in lines_of(note.entry)


def test_a_credit_note_reverses_a_sale(books, senior):
    customer = make_party(books, "Mehta Stores", PartyRole.CUSTOMER, gstin="")
    sales = LedgerAccount.objects.create(firm_id=books.firm_id, client=books, name="Sales", group=LedgerGroup.SALES)
    billing.post_sales(books, customer, [(sales, 5_000_000)], invoice(reference="S-1", cgst=0, sgst=0), membership=senior)

    note = billing.post_credit_note(
        books, customer, [(sales, 1_000_000)], invoice(reference="CN-1", cgst=0, sgst=0), membership=senior
    )

    assert note.kind == BillKind.CREDIT_NOTE and note.direction == Direction.CREDIT
    assert ("Mehta Stores", Direction.CREDIT, 1_000_000) in lines_of(note.entry)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def test_a_payment_settles_a_bill_and_clears_it(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 11_800_000)

    billing.allocate(line, bill=bill, amount_paise=11_800_000)

    assert billing.open_amount(bill) == 0
    assert billing.line_unallocated(line) == 0


def test_part_payments_leave_the_balance_open(books, senior):
    bill = purchase(books, senior)
    first = payment_line(books, bill.party, 5_000_000)
    second = payment_line(books, bill.party, 3_000_000, on=datetime.date(2025, 10, 25))

    billing.allocate(first, bill=bill, amount_paise=5_000_000)
    billing.allocate(second, bill=bill, amount_paise=3_000_000)

    assert billing.open_amount(bill) == 3_800_000


def test_one_payment_can_settle_several_bills(books, senior):
    party = make_party(books)
    a = purchase(books, senior, party, reference="A-1")
    b = purchase(books, senior, party, reference="A-2")
    line = payment_line(books, party, 23_600_000)

    billing.allocate(line, bill=a, amount_paise=11_800_000)
    billing.allocate(line, bill=b, amount_paise=11_800_000)

    assert billing.open_amount(a) == billing.open_amount(b) == 0


def test_allocating_more_than_the_bill_is_refused_in_words(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 20_000_000)

    with pytest.raises(BillingError, match="still open"):
        billing.allocate(line, bill=bill, amount_paise=11_800_001)


def test_allocating_more_than_the_line_is_refused_in_words(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 1_000_000)

    with pytest.raises(BillingError, match="left to allocate"):
        billing.allocate(line, bill=bill, amount_paise=1_000_001)


def test_the_database_refuses_allocations_above_the_bill_even_if_the_service_is_bypassed(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 20_000_000)

    with pytest.raises(DatabaseError, match="exceed"), transaction.atomic():
        BillAllocation.objects.create(
            firm_id=books.firm_id, client=books, line=line, bill=bill, kind=AllocationKind.AGAINST_BILL,
            amount_paise=11_800_001,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_the_database_refuses_allocations_above_the_line_even_if_the_service_is_bypassed(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 1_000_000)

    with pytest.raises(DatabaseError, match="exceed"), transaction.atomic():
        BillAllocation.objects.create(
            firm_id=books.firm_id, client=books, line=line, bill=bill, kind=AllocationKind.AGAINST_BILL,
            amount_paise=1_000_001,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_a_payment_cannot_settle_another_partys_bill(books, senior):
    bill = purchase(books, senior)
    other = purchase(books, senior, make_party(books, "Shah Stationers", gstin="24AAACS1234A1Z9"), reference="X-1")
    line = payment_line(books, other.party, 11_800_000)

    with pytest.raises(BillingError, match="same party"):
        billing.allocate(line, bill=bill, amount_paise=1_000)
    with pytest.raises(DatabaseError, match="same party"), transaction.atomic():
        BillAllocation.objects.create(
            firm_id=books.firm_id, client=books, line=line, bill=bill, kind=AllocationKind.AGAINST_BILL, amount_paise=1_000
        )


def test_a_bill_is_settled_from_the_opposite_side_of_the_ledger(books, senior):
    party = make_party(books)
    first = purchase(books, senior, party, reference="A-1")
    second = purchase(books, senior, party, reference="A-2")
    same_side = second.entry.lines.get(party=party)

    with pytest.raises(BillingError, match="opposite side"):
        billing.allocate(same_side, bill=first, amount_paise=1_000)
    with pytest.raises(DatabaseError, match="opposite side"), transaction.atomic():
        BillAllocation.objects.create(
            firm_id=books.firm_id, client=books, line=same_side, bill=first, kind=AllocationKind.AGAINST_BILL,
            amount_paise=1_000,
        )


def test_a_line_that_is_not_on_the_partys_ledger_cannot_settle_anything(books, senior):
    bill = purchase(books, senior)
    stray = bill.entry.lines.get(ledger_account__name="Purchases")

    with pytest.raises(BillingError, match="names a party"):
        billing.allocate(stray, bill=bill, amount_paise=1_000)


def test_money_paid_before_the_invoice_waits_and_is_then_applied(books, senior):
    party = make_party(books)
    first = purchase(books, senior, party, reference="A-1")
    advance = payment_line(books, party, 5_000_000)
    held = billing.allocate(advance, amount_paise=5_000_000, kind=AllocationKind.ADVANCE)

    billing.apply_unapplied(held, first, amount_paise=3_000_000)

    assert billing.open_amount(first) == 8_800_000
    kinds = sorted(advance.allocations.values_list("kind", "amount_paise"))
    assert kinds == [(AllocationKind.ADVANCE, 2_000_000), (AllocationKind.AGAINST_BILL, 3_000_000)]
    assert billing.line_unallocated(advance) == 0


def test_an_allocation_is_never_edited_only_replaced(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 11_800_000)
    allocation = billing.allocate(line, bill=bill, amount_paise=1_000_000)

    with pytest.raises(DatabaseError, match="never edited"), transaction.atomic():
        BillAllocation.objects.filter(pk=allocation.pk).update(amount_paise=2_000_000)


def test_a_bill_is_never_edited(books, senior):
    bill = purchase(books, senior)

    with pytest.raises(DatabaseError, match="never edited"), transaction.atomic():
        Bill.objects.filter(pk=bill.pk).update(reference="CHANGED")


def test_a_settled_line_cannot_be_deleted_from_under_its_allocation(books, senior):
    bill = purchase(books, senior)
    line = payment_line(books, bill.party, 11_800_000)
    billing.allocate(line, bill=bill, amount_paise=11_800_000)

    with pytest.raises(ProtectedError):
        line.delete()


# ---------------------------------------------------------------------------
# The party's position: ledger against bills
# ---------------------------------------------------------------------------


def test_a_party_with_only_a_bill_reconciles(books, senior):
    bill = purchase(books, senior)
    bill.party.refresh_from_db()

    position = billing.party_position(bill.party)

    assert position.ledger_balance_paise == -11_800_000
    assert position.open_bills_paise == -11_800_000
    assert position.reconciles


def test_a_payment_not_yet_allocated_is_explained_not_lost(books, senior):
    bill = purchase(books, senior)
    bill.party.refresh_from_db()
    line = payment_line(books, bill.party, 11_800_000)

    unallocated = billing.party_position(bill.party)
    billing.allocate(line, bill=bill, amount_paise=11_800_000)
    allocated = billing.party_position(bill.party)

    assert unallocated.ledger_balance_paise == 0 and unallocated.unapplied_paise == 11_800_000
    assert unallocated.reconciles
    assert allocated.ledger_balance_paise == allocated.open_bills_paise == allocated.unapplied_paise == 0
    assert allocated.reconciles


def test_an_opening_balance_that_is_not_broken_into_bills_is_flagged(books, senior):
    bill = purchase(books, senior)
    bill.party.refresh_from_db()
    LedgerOpening.objects.create(
        firm_id=books.firm_id, client=books, ledger=bill.party.ledger, financial_year=2025, signed_paise=-500_000
    )

    position = billing.party_position(bill.party)

    assert not position.reconciles
    assert position.difference_paise == -500_000


def test_a_party_with_no_ledger_yet_has_a_zero_position(books):
    assert billing.party_position(make_party(books)).reconciles


# ---------------------------------------------------------------------------
# Documents, removal, and the edit paths
# ---------------------------------------------------------------------------


def test_a_bill_keeps_its_invoice_file_and_the_file_cannot_be_deleted_from_under_it(books, senior):
    document = Document.objects.create(
        firm_id=books.firm_id, client=books, kind=DocumentKind.PURCHASE_INVOICE, sha256="d" * 64
    )
    bill = purchase(books, senior, document=document)

    assert bill.document_id == document.pk
    with pytest.raises(ProtectedError):
        document.delete()


def test_a_bill_cannot_cite_another_clients_document(books, senior, firm):
    other = Client.objects.create(firm=firm, name="Someone Else", fy_start=datetime.date(2025, 4, 1))
    foreign = Document.objects.create(
        firm_id=books.firm_id, client=other, kind=DocumentKind.PURCHASE_INVOICE, sha256="e" * 64
    )

    with pytest.raises(BillingError, match="different client"):
        purchase(books, senior, document=foreign)


def test_an_unsettled_bill_can_be_removed_with_its_voucher_and_the_change_is_logged(books, senior):
    bill = purchase(books, senior)
    entry_id = bill.entry_id

    billing.remove_bill(bill, membership=senior, note="Entered against the wrong client")

    assert not Bill.objects.exists()
    assert not JournalEntry.objects.filter(pk=entry_id).exists()
    assert not JournalLine.objects.filter(entry_id=entry_id).exists()
    change = EntryChange.objects.get(entry_id=entry_id)
    assert change.action == ChangeAction.REMOVED and change.before["voucher_type"] == VoucherType.PURCHASE


def test_a_settled_bill_cannot_be_removed(books, senior):
    bill = purchase(books, senior)
    billing.allocate(payment_line(books, bill.party, 1_000_000), bill=bill, amount_paise=1_000_000)

    with pytest.raises(BillingError, match="allocated"):
        billing.remove_bill(bill, membership=senior)
    assert Bill.objects.filter(pk=bill.pk).exists()


def test_a_bill_in_signed_off_books_cannot_be_removed_by_the_service_or_by_the_database(books, senior):
    bill = purchase(books, senior)
    sign_off_through(books, datetime.date(2025, 10, 31))

    with pytest.raises(editing.EntryLockedError):
        billing.remove_bill(bill, membership=senior)
    with pytest.raises(DatabaseError, match="signed off"), transaction.atomic():
        Bill.objects.filter(pk=bill.pk).delete()


def test_a_voucher_entry_cannot_be_pushed_down_the_bank_edit_path(books, senior):
    entry = purchase(books, senior).entry

    with pytest.raises(editing.WrongEntryKindError, match="Change it through its bill"):
        editing.remove_entry(entry, actor=senior.user)
    with pytest.raises(editing.WrongEntryKindError):
        editing.revise_in_place(entry, None, actor=senior.user)
    assert JournalEntry.objects.filter(pk=entry.pk).exists()
