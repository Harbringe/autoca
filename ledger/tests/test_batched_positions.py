"""The batched party figures and the two open-item detectors that use them give exactly what the per-party, per-line versions gave, in a fixed
number of queries however many parties there are."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.db.models import F
from django.test.utils import CaptureQueriesContext

from classify.models import PartyRole
from ledger import billing, openitems
from ledger.models import Bill, Direction, JournalLine
from ledger.tests.test_approval import client, firm, ledger, membership_for, senior  # noqa: F401
from ledger.tests.test_billing import (  # noqa: F401  (fixtures and helpers)
    books,
    make_party,
    payment_line,
    purchase,
)

pytestmark = pytest.mark.django_db


def _books_with_activity(books, senior, suppliers=3):
    """Several parties in different states: part-paid, unallocated money, an advance, a customer's receipt, one untouched."""
    parties = []
    for n in range(suppliers):
        party = make_party(books, f"Supplier {n}", gstin=None if n else "27AAACR5055K1Z7")
        first = purchase(books, senior, party, reference=f"S{n}-1")
        second = purchase(books, senior, party, reference=f"S{n}-2")
        paid = payment_line(books, party, 5_000_000, on=datetime.date(2025, 10, 20 + n))
        billing.allocate(paid, bill=first, amount_paise=5_000_000)
        payment_line(books, party, 3_000_000, on=datetime.date(2025, 10, 26))  # money moved, tied to nothing
        advance = payment_line(books, party, 1_000_000, on=datetime.date(2025, 10, 27))
        billing.allocate(advance, amount_paise=1_000_000)  # held on account
        assert second is not None
        parties.append(party)
    customer = make_party(books, "Customer Co", role=PartyRole.CUSTOMER, gstin=None)
    billing.party_ledger_for(customer)  # a party's account is opened the first time it is used; a receipt is used before any bill
    receipt = payment_line(books, customer, 2_000_000, on=datetime.date(2025, 10, 28), direction=Direction.CREDIT)
    assert receipt is not None
    parties.append(customer)
    parties.append(make_party(books, "Nobody Yet", gstin=None))  # no bill, no line, so no ledger
    return parties


def test_the_batched_figures_match_party_position_for_every_party(books, senior):
    parties = _books_with_activity(books, senior)
    positions = billing.party_positions(books)

    with_ledger = [p for p in parties if p.ledger_id]
    assert len(with_ledger) >= 4 and set(positions) == {p.pk for p in with_ledger}
    for party in with_ledger:
        assert positions[party.pk] == billing.party_position(party), party.canonical_name


def test_a_party_without_a_ledger_is_left_out_as_party_position_gives_it_nothing(books, senior):
    parties = _books_with_activity(books, senior, suppliers=1)
    nobody = parties[-1]
    assert nobody.ledger_id is None
    assert nobody.pk not in billing.party_positions(books) and billing.party_position(nobody) == billing.PartyPosition(0, 0, 0)


def test_the_number_of_queries_does_not_grow_with_the_number_of_parties(books, senior):
    _books_with_activity(books, senior, suppliers=1)
    with CaptureQueriesContext(connection) as few:
        billing.party_positions(books)
    for n in range(4):
        party = make_party(books, f"Extra {n}", gstin=None)
        bill = purchase(books, senior, party, reference=f"X{n}")
        billing.allocate(payment_line(books, party, 1_000_000, on=datetime.date(2025, 11, 1 + n)), bill=bill, amount_paise=1_000_000)
    with CaptureQueriesContext(connection) as many:
        billing.party_positions(books)
    assert len(many) == len(few) <= 8


def _reference_unallocated(client):
    """The detector as it was: one query per line for what has been allocated."""
    bill_entries = Bill.objects.filter(firm_id=client.firm_id, client=client, entry__isnull=False).values("entry_id")
    lines = (
        JournalLine.objects.filter(
            firm_id=client.firm_id, entry__client=client, party__isnull=False, ledger_account_id=F("party__ledger_id")
        )
        .exclude(entry_id__in=bill_entries)
        .select_related("entry", "party")
    )
    return sorted(
        (billing.line_unallocated(line), line.entry.entry_date, str(line.entry_id))
        for line in lines
        if billing.line_unallocated(line) > 0
    )


def test_the_unallocated_payments_detector_finds_what_it_always_found(books, senior):
    _books_with_activity(books, senior)
    found = openitems.open_items(books, only=["payment_unallocated"])
    assert found, "the data was built to leave money untied"
    assert sorted((i.amount_paise, i.since, i.link["id"]) for i in found) == _reference_unallocated(books)


def test_the_unallocated_payments_detector_does_not_ask_a_query_per_line(books, senior):
    _books_with_activity(books, senior, suppliers=1)
    with CaptureQueriesContext(connection) as few:
        list(openitems.open_items(books, only=["payment_unallocated"]))
    _books_with_activity(books, senior, suppliers=3)
    with CaptureQueriesContext(connection) as many:
        list(openitems.open_items(books, only=["payment_unallocated"]))
    assert len(many) == len(few)


def test_the_out_of_balance_detector_agrees_with_party_position(books, senior):
    _books_with_activity(books, senior)
    from classify.models import Party

    expected = sorted(
        party.pk.hex
        for party in Party.objects.filter(firm_id=books.firm_id, client=books, ledger__isnull=False)
        if not billing.party_position(party).reconciles
    )
    found = sorted(item.link["id"].replace("-", "") for item in openitems.open_items(books, only=["party_out_of_balance"]))
    assert found == expected  # the same parties, whether that is none or some
