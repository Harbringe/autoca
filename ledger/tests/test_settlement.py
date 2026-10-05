"""A bank row on a party's account settles bills, and a person says which.

The money is posted the way every bank row is (``Dr party / Cr bank``); what is new is that nothing reaches a party's
account without a decision about what it pays, the totals must add up, and an edit or removal of a settled payment
reopens the bills instead of failing or silently keeping them settled.
"""

from __future__ import annotations

import datetime

import pytest

from classify.engine import review, review_queue
from classify.llm import _Chart
from classify.models import ClassificationMethod, LedgerAccount
from classify.treatment import ReviewBand, Treatment
from core.models import Client
from ledger import billing, editing, openitems
from ledger import settlement as settling
from ledger.approval import NotApprovableError, approve, auto_post, correct
from ledger.billing import BillingError, BillInput
from ledger.models import (
    AllocationKind,
    BillAllocation,
    Direction,
    EntryChange,
    JournalEntry,
    VoucherType,
)
from ledger.settlement import Settlement
from ledger.tests.test_approval import (  # noqa: F401
    client,
    firm,
    ledger,
    membership_for,
    senior,
    statement,
)
from ledger.tests.test_billing import lines_of, make_party, purchases

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def the_payment(client):
    """An outgoing NEFT on the fixture statement, and what it moved."""
    row = review_queue(client).filter(transaction__narration__icontains="AXOMB10000000001").first()
    return row, row.transaction.amount_paise


def supplier_bill(client, senior, amount, *, reference="INV-1", party=None, kind="purchase"):
    party = party or make_party(client)
    data = BillInput(reference=reference, bill_date=datetime.date(2025, 4, 1))
    heads = [(purchases(client), amount)]
    post = {"purchase": billing.post_purchase, "debit_note": billing.post_debit_note}[kind]
    return post(client, party, heads, data, membership=senior)


def on_the_partys_account(row, party):
    return review(row, billing.party_ledger_for(party), learn=False)[0]


def settle(*pairs, remainder=None):
    return Settlement(allocations=tuple(pairs), remainder=remainder)


# ---------------------------------------------------------------------------
# A decision is required
# ---------------------------------------------------------------------------


def test_a_row_on_a_partys_account_cannot_be_posted_without_saying_what_it_settles(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount)
    classification = on_the_partys_account(row, bill.party)

    with pytest.raises(NotApprovableError, match="say what it settles"):
        approve(classification, membership=senior)

    assert not JournalEntry.objects.filter(source_transaction=classification.transaction).exists()
    assert not BillAllocation.objects.exists()


def test_a_settlement_on_an_ordinary_row_is_refused(client, statement, senior):
    row, amount = the_payment(client)
    classification = review(row, ledger(client, "Office Expenses"), learn=False)[0]

    with pytest.raises(NotApprovableError, match="not on a party's account"):
        approve(classification, membership=senior, settlement=Settlement())


def test_a_party_account_is_never_posted_by_the_machine(client, statement, senior):
    """Auto-posting is for rows the system is very sure of. A payment on a party's account is never one."""
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount)
    classification = on_the_partys_account(row, bill.party)
    classification.method = ClassificationMethod.RULE
    classification.confidence = 0.95
    classification.review_band = ReviewBand.HIGH
    classification.needs_review = False
    classification.save()

    assert auto_post(classification) is None
    assert not JournalEntry.objects.filter(source_transaction=classification.transaction).exists()


# ---------------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------------


def test_a_payment_that_is_exactly_one_bill_clears_it(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount)
    party = bill.party
    party.refresh_from_db()
    classification = on_the_partys_account(row, party)

    result = approve(classification, membership=senior, settlement=settle((bill, amount)))

    assert result.entry.voucher_type == VoucherType.PAYMENT
    assert lines_of(result.entry) == sorted(
        [(party.ledger.name, Direction.DEBIT, amount), (statement.bank_account.ledger_name, Direction.CREDIT, amount)]
    )
    assert billing.open_amount(bill) == 0
    classification.refresh_from_db()
    assert classification.party_id == party.pk
    assert billing.party_position(party).reconciles
    assert openitems.open_items(client, only=["payment_unallocated"]) == []


def test_a_part_payment_leaves_the_rest_of_the_bill_open_and_the_rest_of_the_money_held(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount * 2)
    bill.party.refresh_from_db()
    classification = on_the_partys_account(row, bill.party)
    half = amount // 2

    approve(classification, membership=senior, settlement=settle((bill, half), remainder=AllocationKind.ON_ACCOUNT))

    assert billing.open_amount(bill) == bill.total_paise - half
    held = BillAllocation.objects.get(kind=AllocationKind.ON_ACCOUNT)
    assert held.amount_paise == amount - half
    assert [i.amount_paise for i in openitems.open_items(client, only=["money_on_account"])] == [amount - half]


def test_money_with_no_bill_at_all_is_held_as_an_advance(client, statement, senior):
    row, amount = the_payment(client)
    party = make_party(client)
    billing.party_ledger_for(party, side="CREDITOR")
    classification = on_the_partys_account(row, party)

    approve(classification, membership=senior, settlement=settle(remainder=AllocationKind.ADVANCE))

    advance = BillAllocation.objects.get()
    assert advance.kind == AllocationKind.ADVANCE and advance.bill_id is None and advance.amount_paise == amount
    assert billing.party_position(party).reconciles


# ---------------------------------------------------------------------------
# What is refused, in words, before anything is written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda bill, amount, other, note: settle((bill, amount + 1)), "more than the"),
        (lambda bill, amount, other, note: settle((bill, amount - 1)), "left over"),
        (lambda bill, amount, other, note: settle((other, amount)), "not one of"),
        (lambda bill, amount, other, note: settle((note, 100)), "same side"),
        (lambda bill, amount, other, note: settle((bill, amount), remainder="FOO"), "on account or as an advance"),
        (lambda bill, amount, other, note: settle((bill, 0)), "above zero"),
    ],
)
def test_a_settlement_that_does_not_add_up_is_refused_and_nothing_is_written(client, statement, senior, make, message):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount * 2)
    party = bill.party
    other = supplier_bill(client, senior, amount, reference="OTH-1", party=make_party(client, "Shah Stationers", gstin=""))
    note = supplier_bill(client, senior, 500_00, reference="DN-1", party=party, kind="debit_note")
    classification = on_the_partys_account(row, party)

    with pytest.raises(BillingError, match=message):
        approve(classification, membership=senior, settlement=make(bill, amount, other, note))

    assert not JournalEntry.objects.filter(source_transaction=classification.transaction).exists()
    assert not BillAllocation.objects.exists()


def test_a_payment_cannot_clear_more_of_a_bill_than_is_open(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount // 2)
    classification = on_the_partys_account(row, bill.party)

    with pytest.raises(BillingError, match="still open"):
        approve(classification, membership=senior, settlement=settle((bill, amount)))


# ---------------------------------------------------------------------------
# Editing and removing a settled payment
# ---------------------------------------------------------------------------


def settled_entry(client, senior, amount_scale=1):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount * amount_scale)
    bill.party.refresh_from_db()
    classification = on_the_partys_account(row, bill.party)
    entry = approve(classification, membership=senior, settlement=settle((bill, amount))).entry
    return entry, bill, amount


def test_removing_a_settled_payment_reopens_the_bill_and_keeps_what_it_settled_in_the_log(client, statement, senior):
    entry, bill, amount = settled_entry(client, senior)
    assert billing.open_amount(bill) == bill.total_paise - amount

    editing.remove_entry(entry, actor=senior.user, note="Wrong row")

    assert billing.open_amount(bill) == bill.total_paise
    assert not BillAllocation.objects.exists()
    change = EntryChange.objects.get(entry_id=entry.pk)
    settled = [a for line in change.before["lines"] for a in line["allocations"]]
    assert settled == [{"bill": str(bill.pk), "kind": AllocationKind.AGAINST_BILL, "amount_paise": amount}]


def test_moving_a_settled_payment_to_an_expense_reopens_the_bill(client, statement, senior):
    entry, bill, amount = settled_entry(client, senior)

    editing.revise_in_place(entry, Treatment(ledger=ledger(client, "Office Expenses")), actor=senior.user)

    assert billing.open_amount(bill) == bill.total_paise
    assert not BillAllocation.objects.exists()
    assert "Office Expenses" in [name for name, _, _ in lines_of(entry)]


def test_a_payment_edited_onto_a_party_account_names_the_party_and_is_then_settled_later(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount)
    party = bill.party
    party.refresh_from_db()
    expense = ledger(client, "Office Expenses")
    entry = approve(review(row, expense, learn=False)[0], membership=senior).entry

    editing.revise_in_place(entry, Treatment(ledger=billing.party_ledger_for(party)), actor=senior.user)

    on_account = entry.lines.get(ledger_account=party.ledger)
    assert on_account.party_id == party.pk
    assert [i.kind for i in openitems.open_items(client, only=["payment_unallocated"])] == ["payment_unallocated"]

    settling.settle_entry(entry, settle((bill, amount)), membership=senior)

    assert billing.open_amount(bill) == 0
    assert openitems.open_items(client, only=["payment_unallocated"]) == []
    with pytest.raises(BillingError, match="already fully allocated"):
        settling.settle_entry(entry, settle((bill, amount)), membership=senior)


def test_a_settled_payment_in_signed_off_books_cannot_be_corrected_here(client, statement, senior):
    entry, bill, amount = settled_entry(client, senior)
    Client.objects.filter(pk=client.pk).update(signed_off_through=entry.entry_date)

    with pytest.raises(NotApprovableError, match="settles bills"):
        correct(entry, membership=senior, treatment=Treatment(ledger=ledger(client, "Office Expenses")))

    assert billing.open_amount(bill) == bill.total_paise - amount


def test_removing_a_statement_removes_its_settlements_and_reopens_the_bills(client, statement, senior):
    from banking.removal import remove_statement

    entry, bill, amount = settled_entry(client, senior)

    remove_statement(statement, actor=senior.user)

    assert billing.open_amount(bill) == bill.total_paise
    assert not BillAllocation.objects.exists()


# ---------------------------------------------------------------------------
# The model never sees, or chooses, a party's account
# ---------------------------------------------------------------------------


def test_the_model_is_never_offered_a_partys_account(client, statement, senior):
    bill = supplier_bill(client, senior, 1_000_00)
    bill.party.refresh_from_db()
    chart = _Chart(
        client,
        list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).select_related("party_record")),
        "",
    )

    offered = {ledger_.name for ledger_ in chart.usable}

    assert bill.party.ledger.name not in offered
    assert "Purchases" in offered
    assert bill.party.ledger.is_party_account


def test_the_bank_and_ordinary_ledgers_are_not_party_accounts(client, statement, senior):
    assert not ledger(client, "Office Expenses").is_party_account
    assert not statement.bank_account.client.ledgers.filter(name=statement.bank_account.ledger_name).first().is_party_account


# ---------------------------------------------------------------------------
# A lesson learned from a party account is never the machine's to apply
# ---------------------------------------------------------------------------


def test_a_lesson_learned_from_a_party_account_never_moves_the_ais_other_entries_onto_it(client, statement, senior):
    """The learning path re-treats the AI's earlier posted entries when a person corrects a similar one. If the lesson is
    "this payee belongs on the supplier's account", that would put payments on a party's account with no decision about
    which bills they settle, so it must leave them where they are."""
    from classify.models import ClassificationRule, MatchType, RuleSource
    from classify.models import Direction as RuleDirection
    from classify.narration import normalise
    from ledger.learning import apply_learned_rule

    row, amount = the_payment(client)
    classification = review(row, ledger(client, "Office Expenses"), learn=False)[0]
    entry = approve(classification, membership=senior).entry
    classification.refresh_from_db()
    classification.method = ClassificationMethod.RULE  # the AI placed it, not a person
    classification.counterparty = "RAVI TRADERS"
    classification.save()
    bill = supplier_bill(client, senior, amount)
    bill.party.refresh_from_db()
    rule = ClassificationRule.objects.create(
        firm_id=client.firm_id, client=client, ledger=bill.party.ledger, party=bill.party,
        match_type=MatchType.PARTY_EQUALS, pattern=normalise("RAVI TRADERS"), direction=RuleDirection.ANY,
        source=RuleSource.LEARNED, priority=200, confidence=0.9,
    )

    assert apply_learned_rule(client, rule) == 0

    assert "Office Expenses" in [name for name, _, _ in lines_of(entry)]
    assert bill.party.ledger.name not in [name for name, _, _ in lines_of(entry)]


def test_the_machine_may_not_move_an_entry_onto_a_party_account_or_undo_a_settlement(client, statement, senior):
    entry, bill, amount = settled_entry(client, senior)
    expense = ledger(client, "Office Expenses")

    with pytest.raises(editing.MachineEditRefusedError, match="a person allocated"):
        editing.revise_in_place(entry, Treatment(ledger=expense), actor=None, method=ClassificationMethod.RULE)
    assert billing.open_amount(bill) == bill.total_paise - amount

    other_row = review_queue(client).exclude(transaction=entry.source_transaction).first()
    other = approve(review(other_row, expense, learn=False)[0], membership=senior).entry
    bill.party.refresh_from_db()
    with pytest.raises(editing.MachineEditRefusedError, match="own account"):
        editing.revise_in_place(other, Treatment(ledger=bill.party.ledger), actor=None, method=ClassificationMethod.RULE)


def test_a_person_may_still_move_an_entry_onto_a_party_account(client, statement, senior):
    row, amount = the_payment(client)
    bill = supplier_bill(client, senior, amount)
    bill.party.refresh_from_db()
    entry = approve(review(row, ledger(client, "Office Expenses"), learn=False)[0], membership=senior).entry

    editing.revise_in_place(entry, Treatment(ledger=bill.party.ledger), actor=senior.user)

    assert bill.party.ledger.name in [name for name, _, _ in lines_of(entry)]
