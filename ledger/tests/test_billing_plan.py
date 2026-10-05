"""Where a rupee goes on an invoice: the planner, with no database.

``plan_purchase`` and its siblings turn invoice figures into debit and credit lines. The rules that matter -- GST,
reverse charge, TDS, rounding, returns -- are all arithmetic, so they are proved here without a database, and every plan
must balance whatever the inputs.
"""

from __future__ import annotations

import itertools

import pytest

from ledger.billing import (
    INPUT,
    INPUT_RCM,
    OUTPUT,
    PARTY,
    PAYABLE_RCM,
    ROUND_OFF,
    TDS_PAYABLE,
    BillingError,
    plan_credit_note,
    plan_debit_note,
    plan_purchase,
    plan_sales,
)
from ledger.models import Direction

DR, CR = Direction.DEBIT, Direction.CREDIT
PURCHASES = "Purchases"
SALES = "Sales"


def by_ledger(plan):
    """``{ledger: (direction, amount)}``: easier to read than a list when every ledger appears once."""
    return {line.ledger: (line.direction, line.amount_paise) for line in plan.lines}


def test_the_ravi_traders_purchase():
    """1,00,000 plus 18,000 GST: the supplier is owed the lot, and the tax has its own ledger."""
    plan = plan_purchase([(PURCHASES, 10_000_000)], cgst=900_000, sgst=900_000)

    assert by_ledger(plan) == {
        PURCHASES: (DR, 10_000_000),
        INPUT["cgst"]: (DR, 900_000),
        INPUT["sgst"]: (DR, 900_000),
        PARTY: (CR, 11_800_000),
    }
    assert plan.party_paise == 11_800_000
    assert plan.debits == plan.credits == 11_800_000


def test_interstate_tax_goes_to_input_igst():
    plan = plan_purchase([(PURCHASES, 10_000_000)], igst=1_800_000)

    assert by_ledger(plan)[INPUT["igst"]] == (DR, 1_800_000)
    assert INPUT["cgst"] not in by_ledger(plan)


def test_several_heads_each_get_their_own_line():
    plan = plan_purchase([("Freight", 200_000), (PURCHASES, 800_000)], cgst=90_000, sgst=90_000)

    assert [line.ledger for line in plan.lines if line.direction == DR][:2] == ["Freight", PURCHASES]
    assert plan.party_paise == 1_180_000


def test_reverse_charge_credits_the_supplier_only_the_taxable_value():
    """The client owes the GST itself: it nets to nothing in the books and is picked up in the return."""
    plan = plan_purchase([(PURCHASES, 10_000_000)], cgst=900_000, sgst=900_000, rcm=True)

    assert plan.party_paise == 10_000_000
    assert by_ledger(plan)[INPUT_RCM] == (DR, 1_800_000)
    assert by_ledger(plan)[PAYABLE_RCM] == (CR, 1_800_000)
    assert INPUT["cgst"] not in by_ledger(plan)
    assert all(line.rcm for line in plan.lines if line.ledger in (INPUT_RCM, PAYABLE_RCM))


def test_tds_is_deducted_at_booking_and_the_supplier_is_credited_the_net():
    plan = plan_purchase([("Professional Fees", 5_000_000)], igst=900_000, tds=500_000, tds_section="194J")

    assert plan.party_paise == 5_400_000
    assert by_ledger(plan)[TDS_PAYABLE] == (CR, 500_000)
    assert [line.tds_section for line in plan.lines if line.ledger == TDS_PAYABLE] == ["194J"]
    assert plan.debits == plan.credits == 5_900_000


@pytest.mark.parametrize(
    ("round_off", "side", "party"),
    [(40, DR, 1_000_040), (-40, CR, 999_960)],
)
def test_rounding_is_booked_to_round_off_on_the_side_that_balances(round_off, side, party):
    plan = plan_purchase([(PURCHASES, 1_000_000)], round_off=round_off)

    assert by_ledger(plan)[ROUND_OFF] == (side, 40)
    assert plan.party_paise == party
    assert plan.debits == plan.credits


def test_a_sales_invoice_debits_the_customer_and_credits_sales_and_output_tax():
    plan = plan_sales([(SALES, 10_000_000)], cgst=900_000, sgst=900_000)

    assert by_ledger(plan) == {
        PARTY: (DR, 11_800_000),
        SALES: (CR, 10_000_000),
        OUTPUT["cgst"]: (CR, 900_000),
        OUTPUT["sgst"]: (CR, 900_000),
    }


@pytest.mark.parametrize("round_off", [25, -25])
def test_a_sales_invoice_rounds_on_the_side_that_balances(round_off):
    plan = plan_sales([(SALES, 1_000_000)], round_off=round_off)

    assert plan.party_paise == 1_000_000 + round_off
    assert plan.debits == plan.credits


def test_a_debit_note_is_the_purchase_the_other_way_round():
    purchase = plan_purchase([(PURCHASES, 10_000_000)], cgst=900_000, sgst=900_000)
    note = plan_debit_note([(PURCHASES, 10_000_000)], cgst=900_000, sgst=900_000)

    assert by_ledger(note)[PARTY] == (DR, 11_800_000)
    assert by_ledger(note)[PURCHASES] == (CR, 10_000_000)
    assert by_ledger(note)[INPUT["cgst"]] == (CR, 900_000)
    assert note.party_paise == purchase.party_paise


def test_a_credit_note_is_the_sale_the_other_way_round():
    note = plan_credit_note([(SALES, 10_000_000)], igst=1_800_000)

    assert by_ledger(note)[PARTY] == (CR, 11_800_000)
    assert by_ledger(note)[SALES] == (DR, 10_000_000)
    assert by_ledger(note)[OUTPUT["igst"]] == (DR, 1_800_000)


@pytest.mark.parametrize("extra", [{"tds": 100}, {"rcm": True}])
def test_a_debit_note_does_not_carry_tds_or_reverse_charge_yet(extra):
    with pytest.raises(BillingError, match="debit note"):
        plan_debit_note([(PURCHASES, 100_000)], **extra)


@pytest.mark.parametrize(
    ("heads", "kwargs", "message"),
    [
        ([], {}, "at least one head"),
        ([(PURCHASES, 0)], {}, "above zero"),
        ([(PURCHASES, -5)], {}, "above zero"),
        ([(PURCHASES, 100.5)], {}, "whole paise"),
        ([(PURCHASES, 1000)], {"cgst": -1}, "CGST"),
        ([(PURCHASES, 1000)], {"cgst": 90, "igst": 180}, "not both"),
        ([(PURCHASES, 1000)], {"tds": 1000}, "owed nothing"),
        ([(PURCHASES, 1000)], {"tds": 2000}, "owed nothing"),
    ],
)
def test_bad_figures_are_refused_with_a_reason(heads, kwargs, message):
    with pytest.raises(BillingError, match=message):
        plan_purchase(heads, **kwargs)


def test_every_combination_of_tax_rounding_and_tds_balances():
    """The property the database would otherwise have to catch at commit."""
    for rcm, igst, round_off, tds in itertools.product([False, True], [False, True], [-99, 0, 99], [0, 150]):
        tax = {"igst": 1_800} if igst else {"cgst": 900, "sgst": 900}
        plan = plan_purchase([(PURCHASES, 10_000)], round_off=round_off, tds=tds, rcm=rcm, **tax)
        assert plan.debits == plan.credits, (rcm, igst, round_off, tds)
        assert plan.party_paise > 0


def test_every_line_is_a_positive_whole_amount():
    plan = plan_purchase([(PURCHASES, 10_000)], cgst=900, sgst=900, round_off=-3, tds=100, rcm=False)

    assert all(isinstance(line.amount_paise, int) and line.amount_paise > 0 for line in plan.lines)
