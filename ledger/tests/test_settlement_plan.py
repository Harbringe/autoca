"""Which bills a payment most plausibly clears: the matcher, with no database.

It only proposes. A person confirms every settlement, because a payment allocated to the wrong bill still balances every
total. These tests pin how it decides, in order of how sure it can be: one bill that is exactly the payment, a small set
that adds up to it exactly, and otherwise the oldest bills first.
"""

from __future__ import annotations

import datetime

import pytest

from ledger.settlement import MAX_POOL, OpenBill, propose


def bill(name, open_paise, month=1, day=1):
    return OpenBill(id=name, reference=name, bill_date=datetime.date(2025, month, day), open_paise=open_paise)


def test_one_bill_that_is_exactly_the_payment_is_the_match():
    bills = [bill("A", 100), bill("B", 250), bill("C", 100)]

    proposal = propose(250, bills)

    assert proposal.allocations == (("B", 250),)
    assert proposal.remainder_paise == 0 and proposal.basis == "exact_one"


def test_when_two_bills_are_exactly_the_payment_the_older_one_is_taken():
    bills = [bill("NEW", 100, month=6), bill("OLD", 100, month=2)]

    assert propose(100, bills).allocations == (("OLD", 100),)


def test_a_set_of_bills_that_adds_up_exactly_is_found():
    bills = [bill("A", 100, month=1), bill("B", 150, month=2), bill("C", 400, month=3)]

    proposal = propose(250, bills)

    assert proposal.allocations == (("A", 100), ("B", 150))
    assert proposal.remainder_paise == 0 and proposal.basis == "exact_set"


def test_the_oldest_exact_set_wins():
    bills = [bill("A", 100, month=1), bill("B", 200, month=2), bill("C", 200, month=3), bill("D", 100, month=4)]

    assert propose(300, bills).allocations == (("A", 100), ("B", 200))


def test_with_no_exact_match_the_oldest_bills_are_filled_first_and_the_last_part_paid():
    bills = [bill("A", 100, month=1), bill("B", 100, month=2), bill("C", 100, month=3)]

    proposal = propose(250, bills)

    assert proposal.allocations == (("A", 100), ("B", 100), ("C", 50))
    assert proposal.remainder_paise == 0 and proposal.basis == "oldest_first"


def test_a_payment_larger_than_everything_owed_leaves_the_rest_to_be_held():
    proposal = propose(500, [bill("A", 100)])

    assert proposal.allocations == (("A", 100),)
    assert proposal.remainder_paise == 400 and proposal.basis == "oldest_first"


def test_no_open_bills_means_the_whole_payment_is_left_to_be_held():
    proposal = propose(500, [])

    assert proposal.allocations == () and proposal.remainder_paise == 500 and proposal.basis == "none"


def test_a_bill_with_nothing_open_is_ignored():
    proposal = propose(100, [bill("PAID", 0, month=1), bill("OPEN", 100, month=2)])

    assert proposal.allocations == (("OPEN", 100),)


def test_a_search_is_only_made_among_the_oldest_bills():
    """A payment that clears many invoices to the paisa is one a person should look at, so the search is small."""
    # Forty bills of 100 can cover 3,000, but no six of the twenty oldest add up to it exactly.
    bills = [bill(f"B{n:02d}", 100, month=1 + n // 28, day=1 + n % 28) for n in range(MAX_POOL * 2)]

    proposal = propose(3000, bills)

    assert proposal.basis == "oldest_first"
    assert sum(paise for _, paise in proposal.allocations) == 3000
    assert [name for name, _ in proposal.allocations][:3] == ["B00", "B01", "B02"]


def test_the_same_inputs_always_give_the_same_proposal():
    bills = [bill("A", 100, month=1), bill("B", 100, month=1), bill("C", 300, month=2)]

    assert propose(200, bills) == propose(200, list(reversed(bills)))


@pytest.mark.parametrize("amount", [0, -5, 10.5])
def test_a_payment_must_be_a_positive_whole_amount(amount):
    with pytest.raises(ValueError, match="above zero"):
        propose(amount, [bill("A", 100)])
