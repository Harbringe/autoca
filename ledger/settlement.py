"""Settling a party's bills with money that moved through the bank.

A bank row placed on a supplier's or customer's own account is not an expense: it pays what was owed. This module is
the missing step between "the money moved" and "that invoice is paid": which bills does this payment clear, or is it held
on account or as an advance for a bill that has not arrived.

**A person decides, every time.** The matcher below only *proposes*. A payment that is allocated to the wrong bill still
balances every total, and only shows up months later as the wrong party owing the wrong amount, so nothing is ever
allocated, or posted, to a party's account without a person having said what it settles. That is deliberately stricter
than the automatic posting bank rows otherwise get, and it can be relaxed later once the matcher has a track record.

Two halves, like ``ledger.billing``: ``propose`` is pure arithmetic with no database, and the rest writes allocations.
"""

from __future__ import annotations

import datetime
import itertools
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import BigIntegerField, F, Sum, Value
from django.db.models.functions import Coalesce

from core.access import require_posting_rights
from core.rbac import require_permission
from ledger import billing
from ledger.models import AllocationKind, Bill, Direction, JournalLine

#: How many of the oldest open bills are searched for a set that adds up to the payment exactly, and how big a set.
#: Small on purpose: a payment that clears eight invoices to the paisa is a payment a person should look at.
MAX_POOL = 20
MAX_SET = 6

#: What may be done with the part of a payment no bill takes.
HOLD_KINDS = (AllocationKind.ON_ACCOUNT, AllocationKind.ADVANCE)


# ---------------------------------------------------------------------------
# The matcher: pure, no database
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenBill:
    """What the matcher needs to know about a bill that still owes something."""

    id: object
    reference: str
    bill_date: datetime.date
    open_paise: int


@dataclass(frozen=True)
class Proposal:
    """What the matcher would settle, and why. A suggestion a person confirms or changes."""

    #: ``(bill id, paise)`` pairs, oldest bill first.
    allocations: tuple[tuple[object, int], ...]
    #: What is left after the bills, to be held on account or as an advance.
    remainder_paise: int
    #: ``exact_one``, ``exact_set``, ``oldest_first`` or ``none``. Says how sure to be.
    basis: str


def propose(amount_paise: int, bills: Sequence[OpenBill]) -> Proposal:
    """Which open bills this amount most plausibly clears.

    In order of how sure it can be: one bill whose open amount is exactly the payment; a small set of bills that add up to
    it exactly; otherwise the oldest bills filled in date order, the last one part-paid, which is how most suppliers apply
    a payment. Bills with nothing open are ignored. Ties go to the older bill.
    """
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise ValueError("A payment to match must be an amount above zero, in whole paise.")

    live = sorted((b for b in bills if b.open_paise > 0), key=lambda b: (b.bill_date, b.reference))

    for bill in live:
        if bill.open_paise == amount_paise:
            return Proposal(((bill.id, amount_paise),), 0, "exact_one")

    pool = live[:MAX_POOL]
    for size in range(2, min(len(pool), MAX_SET) + 1):
        for combo in itertools.combinations(pool, size):
            if sum(b.open_paise for b in combo) == amount_paise:
                return Proposal(tuple((b.id, b.open_paise) for b in combo), 0, "exact_set")

    left = amount_paise
    taken: list[tuple[object, int]] = []
    for bill in live:
        if left == 0:
            break
        part = min(left, bill.open_paise)
        taken.append((bill.id, part))
        left -= part
    return Proposal(tuple(taken), left, "oldest_first" if taken else "none")


# ---------------------------------------------------------------------------
# A person's decision, and applying it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settlement:
    """What a person decided a payment or receipt on a party's account is for."""

    #: ``(bill, paise)``: the bills it clears, and how much of each.
    allocations: tuple[tuple[Bill, int], ...] = field(default_factory=tuple)
    #: What to do with the part no bill takes: ``ON_ACCOUNT`` or ``ADVANCE``. Required if anything is left.
    remainder: str | None = None


def open_bills_for(party, line_direction: str) -> list[Bill]:
    """The party's bills a line on the given side can settle, with what is still open on each, oldest first.

    A bill is settled from the opposite side of the party's account, so a payment (a debit on the account) can settle
    purchases and credit notes, and a receipt can settle sales and debit notes. Each bill carries ``open_paise``.
    """
    return list(
        Bill.objects.filter(firm_id=party.firm_id, party=party)
        .exclude(direction=line_direction)
        .annotate(settled=Coalesce(Sum("allocations__amount_paise"), Value(0), output_field=BigIntegerField()))
        .annotate(open_paise=F("total_paise") - F("settled"))
        .filter(open_paise__gt=0)
        .order_by("bill_date", "reference")
    )


def propose_for(party, line_direction: str, amount_paise: int) -> tuple[list[Bill], Proposal]:
    """The party's open bills for this payment, and what the matcher would settle. A suggestion, not a decision."""
    bills = open_bills_for(party, line_direction)
    proposal = propose(
        amount_paise, [OpenBill(id=b.pk, reference=b.reference, bill_date=b.bill_date, open_paise=b.open_paise) for b in bills]
    )
    return bills, proposal


def party_for_ledger(ledger):
    """The party whose own account this ledger is, or None."""
    return ledger.party_record if ledger is not None and ledger.is_party_account else None


def needed_message(party, amount_paise: int) -> str:
    return (
        f"This is on {party.canonical_name}'s account, so say what it settles: which bills it pays, or whether the "
        f"{billing_amount(amount_paise)} is held on account or as an advance. Nothing is posted to a party's account "
        f"without that."
    )


def billing_amount(paise: int) -> str:
    from core.money import format_inr

    return format_inr(paise)


def validate(party, line_direction: str, amount_paise: int, settlement: Settlement) -> None:
    """Refuse a settlement that does not add up, before anything is written, saying why."""
    wanted = Counter()
    for bill, paise in settlement.allocations:
        if not isinstance(paise, int) or paise <= 0:
            raise billing.BillingError("Every amount settled against a bill must be above zero, in whole paise.")
        if bill.party_id != party.pk:
            raise billing.BillingError(f"{bill.reference!r} is not one of {party.canonical_name}'s bills.")
        if bill.direction == line_direction:
            raise billing.BillingError(
                f"{bill.reference!r} sits on the same side of the account as this payment, so it cannot settle it."
            )
        wanted[bill.pk] += paise

    by_pk = {bill.pk: bill for bill, _ in settlement.allocations}
    for pk, paise in wanted.items():
        open_now = billing.open_amount(by_pk[pk])
        if paise > open_now:
            raise billing.BillingError(
                f"Only {billing_amount(open_now)} of {by_pk[pk].reference!r} is still open, not {billing_amount(paise)}."
            )

    total = sum(wanted.values())
    if total > amount_paise:
        raise billing.BillingError(
            f"The bills add up to {billing_amount(total)}, more than the {billing_amount(amount_paise)} that moved."
        )
    left = amount_paise - total
    if left and settlement.remainder not in HOLD_KINDS:
        raise billing.BillingError(
            f"{billing_amount(left)} is left over after the bills. Say whether it is held on account or is an advance."
        )
    if settlement.remainder is not None and settlement.remainder not in HOLD_KINDS:
        raise billing.BillingError("What is left over is held either on account or as an advance.")


def apply(line: JournalLine, settlement: Settlement, amount_paise: int) -> None:
    """Write the allocations a validated settlement describes, against the party's line.

    ``amount_paise`` is how much of the line the settlement accounts for: all of it for a row being approved, and only
    the still-unallocated part for an entry settled later. Whatever the bills do not take is held, as the settlement says.
    """
    total = 0
    for bill, paise in settlement.allocations:
        billing.allocate(line, bill=bill, amount_paise=paise)
        total += paise
    left = amount_paise - total
    if left > 0:
        billing.allocate(line, amount_paise=left, kind=settlement.remainder)


@transaction.atomic
def settle_entry(entry, settlement: Settlement, *, membership) -> int:
    """Settle the party line of an entry that is already posted and not yet fully allocated.

    For a payment posted before this existed, one whose treatment was edited (which clears its allocations), or one a
    person chose to leave and come back to. Allocates whatever of the line is still unallocated; returns how many paise.
    """
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, entry.client)

    line = next(
        (
            candidate
            for candidate in entry.lines.select_related("ledger_account")
            if candidate.ledger_account.is_party_account and candidate.party_id
        ),
        None,
    )
    if line is None:
        raise billing.BillingError("This entry is not on a party's account, so there is nothing to settle.")

    left = billing.line_unallocated(line)
    if left <= 0:
        raise billing.BillingError("This entry is already fully allocated.")
    validate(line.party, line.direction, left, settlement)
    apply(line, settlement, left)
    return left


def line_direction_for(transaction_row) -> str:
    """Money out of the bank is a debit on the other side's account; money in is a credit."""
    return Direction.DEBIT if transaction_row.is_debit else Direction.CREDIT
