"""One list of everything that does not yet tie out.

A raw document is an island, and an island that nobody can see is the worst kind. So instead of every module reporting its
own leftovers in its own screen, each registers a small *detector* here, and ``open_items`` collects them all. The month-end
close is built from this one list, and sign-off will be gated on it being clear or explained.

Items are **computed, never stored**. A stored list goes stale the moment a payment is allocated; a computed one is right
by construction. Each carries enough to fix it: what it is, the amount, how old, and where to go.

Adding a document type means adding detectors for what can be left unmatched about it. It does not mean adding a report.
That is the difference between reconciling documents into one set of books and collecting more islands.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from django.db.models import F, Q, Sum

from core.money import format_inr
from ledger import billing
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    EntryKind,
    JournalEntry,
    JournalLine,
)


@dataclass(frozen=True)
class OpenItem:
    """One thing that needs a person: what it is, how much, how long, and where to fix it."""

    kind: str
    client_id: object
    #: A sentence a CA can read: what is unmatched and about whom.
    summary: str
    amount_paise: int | None = None
    #: The date it dates from, so the list can be sorted oldest first and aged.
    since: datetime.date | None = None
    #: What to open to fix it: ``{"type": "bill", "id": ...}``.
    link: dict | None = None


#: kind -> (title, detector). A detector takes a client and yields items.
_DETECTORS: dict[str, tuple[str, Callable[[object], Iterable[OpenItem]]]] = {}


def detector(kind: str, title: str):
    """Register a function that finds one kind of open item for a client."""

    def register(function):
        if kind in _DETECTORS:
            raise ValueError(f"An open-item detector for {kind!r} is already registered.")
        _DETECTORS[kind] = (title, function)
        return function

    return register


def kinds() -> dict[str, str]:
    """``{kind: title}`` for everything that can be reported."""
    return {kind: title for kind, (title, _) in _DETECTORS.items()}


def open_items(client, *, only: Iterable[str] | None = None) -> list[OpenItem]:
    """Everything open for ``client``, oldest first. A detector that raises is a bug, not an empty result."""
    wanted = set(only) if only is not None else None
    items: list[OpenItem] = []
    for kind, (_, function) in _DETECTORS.items():
        if wanted is None or kind in wanted:
            items.extend(function(client))
    return sorted(items, key=lambda item: (item.since or datetime.date.max, item.kind, item.summary))


# ---------------------------------------------------------------------------
# Detectors for the party accounting in this phase
# ---------------------------------------------------------------------------


@detector("bill_without_document", "A bill with no invoice file behind it")
def bills_without_a_document(client):
    """The books say an invoice exists and nothing proves it. Allowed, but never silent."""
    bills = Bill.objects.filter(
        firm_id=client.firm_id, client=client, document__isnull=True, reading__isnull=True
    ).exclude(kind=BillKind.OPENING).select_related("party")
    for bill in bills:
        yield OpenItem(
            kind="bill_without_document",
            client_id=client.pk,
            summary=f"{bill.get_kind_display()} {bill.reference} of {bill.party.canonical_name} has no invoice file.",
            amount_paise=bill.total_paise,
            since=bill.bill_date,
            link={"type": "bill", "id": str(bill.pk)},
        )


@detector("payment_unallocated", "Money moved on a party's account that is not tied to any bill")
def unallocated_settlements(client):
    """A line on a party's ledger that no allocation accounts for in full.

    The ledger balances regardless, which is exactly why this is easy to miss: the wrong party can owe the wrong amount
    and every total still adds up.
    """
    bill_entries = Bill.objects.filter(firm_id=client.firm_id, client=client, entry__isnull=False).values("entry_id")
    # Only lines on the party's OWN ledger. The bank flow also tags a party on the expense line of a payment booked
    # straight to an expense head; that is not money on a party's account and must not be reported as such.
    lines = (
        JournalLine.objects.filter(
            firm_id=client.firm_id, entry__client=client, party__isnull=False, ledger_account_id=F("party__ledger_id")
        )
        .exclude(entry_id__in=bill_entries)
        .select_related("entry", "party")
    )
    for line in lines:
        left = billing.line_unallocated(line)
        if left > 0:
            yield OpenItem(
                kind="payment_unallocated",
                client_id=client.pk,
                summary=f"{left} paise on {line.party.canonical_name}'s account ({line.entry.entry_date:%d-%m-%Y}) "
                f"is not allocated to any bill.",
                amount_paise=left,
                since=line.entry.entry_date,
                link={"type": "entry", "id": str(line.entry_id)},
            )


@detector("money_on_account", "Money held on account or as an advance, never applied to a bill")
def money_on_account(client):
    held = BillAllocation.objects.filter(
        firm_id=client.firm_id, client=client, kind__in=[AllocationKind.ON_ACCOUNT, AllocationKind.ADVANCE]
    ).select_related("line__entry", "line__party")
    for allocation in held:
        yield OpenItem(
            kind="money_on_account",
            client_id=client.pk,
            summary=f"{allocation.amount_paise} paise {allocation.get_kind_display().lower()} on "
            f"{allocation.line.party.canonical_name}'s account has not been applied to a bill.",
            amount_paise=allocation.amount_paise,
            since=allocation.line.entry.entry_date,
            link={"type": "entry", "id": str(allocation.line.entry_id)},
        )


@detector("party_out_of_balance", "A party whose ledger and bills disagree")
def parties_out_of_balance(client):
    """The first control-account check: every party's ledger must equal what its bills and settlements explain."""
    from classify.models import Party

    for party in Party.objects.filter(firm_id=client.firm_id, client=client, ledger__isnull=False).select_related("ledger"):
        position = billing.party_position(party)
        if not position.reconciles:
            yield OpenItem(
                kind="party_out_of_balance",
                client_id=client.pk,
                summary=f"{party.canonical_name}'s ledger and bills differ by {abs(position.difference_paise)} paise.",
                amount_paise=abs(position.difference_paise),
                link={"type": "party", "id": str(party.pk)},
            )


@detector("invoice_unbooked", "An uploaded invoice nobody has booked")
def invoices_waiting(client):
    """A file that arrived and has not become a bill, been attached to one, or been set aside. Never left unseen."""
    from ledger import invoice_intake
    from ledger.models import InvoiceReading, ReadingStatus

    for reading in InvoiceReading.objects.filter(
        firm_id=client.firm_id, client=client, status=ReadingStatus.OPEN
    ).select_related("document"):
        name = reading.document.original_filename or "An invoice"
        if reading.unreadable_reason:
            summary = f"{name} is a scan or photo and cannot be read yet. Key it in by hand; the file stays attached."
            amount = None
        else:
            fields = invoice_intake.fields_of(reading)
            amount = fields.get("total_paise")
            summary = (
                f"{name} has been read and is waiting to be booked."
                if reading.proved
                else f"{name} was read but does not add up; check it before booking."
            )
        yield OpenItem(
            kind="invoice_unbooked",
            client_id=client.pk,
            summary=summary,
            amount_paise=amount,
            since=reading.created_at.date(),
            link={"type": "invoice", "id": str(reading.pk)},
        )


@detector("party_opening_unbilled", "An opening balance not yet broken into bills")
def openings_without_bills(client):
    """A party's imported opening balance that the bills do not account for.

    Until it is broken into the invoices it is made of, no payment can be settled against what is really outstanding.
    """
    from classify.models import Party
    from ledger import openings

    for party in Party.objects.filter(firm_id=client.firm_id, client=client, ledger__isnull=False).select_related("ledger"):
        standing = openings.opening_standing(party)
        if standing.direction and standing.remaining_paise > 0:
            yield OpenItem(
                kind="party_opening_unbilled",
                client_id=client.pk,
                summary=(
                    f"{party.canonical_name}'s opening balance of {format_inr(abs(standing.opening_paise))} has "
                    f"{format_inr(standing.remaining_paise)} not yet broken into bills."
                ),
                amount_paise=standing.remaining_paise,
                since=datetime.date(standing.financial_year, 4, 1),
                link={"type": "party", "id": str(party.pk)},
            )


def _live_entry(transaction_row):
    """The entry that currently stands for a bank row, ignoring corrected ones."""
    return JournalEntry.objects.filter(
        source_transaction=transaction_row, entry_kind=EntryKind.BANK, superseded_by_set__isnull=True
    ).first()


def _classified_rows(client):
    from classify.models import TransactionClassification

    return TransactionClassification.objects.filter(
        firm_id=client.firm_id, transaction__bank_account__client=client, ledger__isnull=False, party__isnull=False
    ).select_related("transaction", "party", "ledger")


@detector("payment_bypasses_bills", "A payment to a party that has bills, booked to an expense instead")
def payments_that_bypass_bills(client):
    """The party has invoices on the books, but this payment did not go against them.

    That is the one place a party-wise ledger can quietly stop being true: the money moved, the bill is still shown as
    owing, and the party's account disagrees with the bank. A payment may legitimately have no invoice (rent, a small cash
    item), but then someone says so, and until they do it is listed. A party with no bills is not listed: invoice-wise
    accounting has not started for it, and flagging every old payment would bury the ones that matter.
    """
    from django.db.models import Exists, OuterRef

    from classify.models import BillStatus, LedgerGroup, PartyRole

    rows = (
        _classified_rows(client)
        .filter(bill_status=BillStatus.UNSTATED, ledger__party_record__isnull=True)
        .exclude(ledger__group__in=[LedgerGroup.BANK, LedgerGroup.CASH, LedgerGroup.BANK_OD, LedgerGroup.LOAN])
        .filter(Exists(Bill.objects.filter(party_id=OuterRef("party_id"))))
        .filter(
            Q(transaction__debit_paise__gt=0, party__role__in=[PartyRole.VENDOR, PartyRole.BOTH])
            | Q(transaction__credit_paise__gt=0, party__role__in=[PartyRole.CUSTOMER, PartyRole.BOTH])
        )
        .order_by("transaction__value_date")
    )
    for row in rows:
        entry = _live_entry(row.transaction)
        if entry is None:
            continue
        verb = "paid" if row.transaction.is_debit else "received"
        yield OpenItem(
            kind="payment_bypasses_bills",
            client_id=client.pk,
            summary=f"{row.party.canonical_name} has bills, but {format_inr(row.transaction.amount_paise)} {verb} on "
            f"{row.transaction.value_date:%d-%m-%Y} was booked to {row.ledger.name}, not against them.",
            amount_paise=row.transaction.amount_paise,
            since=row.transaction.value_date,
            link={"type": "entry", "id": str(entry.pk)},
        )


@detector("payment_needs_invoice", "A payment waiting for its invoice")
def payments_needing_an_invoice(client):
    from classify.models import BillStatus

    for row in _classified_rows(client).filter(bill_status=BillStatus.NEEDS_INVOICE).order_by("transaction__value_date"):
        entry = _live_entry(row.transaction)
        if entry is None:
            continue
        yield OpenItem(
            kind="payment_needs_invoice",
            client_id=client.pk,
            summary=f"{format_inr(row.transaction.amount_paise)} paid to {row.party.canonical_name} on "
            f"{row.transaction.value_date:%d-%m-%Y} is waiting for its invoice.",
            amount_paise=row.transaction.amount_paise,
            since=row.transaction.value_date,
            link={"type": "entry", "id": str(entry.pk)},
        )


def total_held(client) -> int:
    """Convenience for a summary: how much sits on account across all parties."""
    return (
        BillAllocation.objects.filter(
            firm_id=client.firm_id, client=client, kind__in=[AllocationKind.ON_ACCOUNT, AllocationKind.ADVANCE]
        ).aggregate(total=Sum("amount_paise"))["total"]
        or 0
    )
