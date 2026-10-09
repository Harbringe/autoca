"""Matching invoices to the bank rows that paid them, so neither is left standing alone.

An invoice is booked on the party's account, and the payment arrives as a bank row. Without a link the party's account shows
the invoice still owing while the bank statement shows it paid (or the payment sits in an expense head and counts the cost
twice). This module finds the pairs and settles them.

**It decides only when nothing is left to decide.** A pair is settled by the system when all of these hold:

* the amount is the bill's open amount to the paise, in the right direction (money out for a purchase, in for a sale), or,
  for a sales bill to a customer whose TDS section is on record, that amount less the TDS the section allows (to the rupee);
* the row's date is within a sensible window of the invoice (a little before it, for an advance, to a few months after);
* the row is the party's: the classification already names that party, or the narration contains the party's full name or
  one of its confirmed spellings (``PartyAlias``). Similar-looking is never enough;
* the pair is unique both ways: no other row could be this bill's payment, and no other bill could be this row's;
* the row is not posted yet, not placed by a person, and the books are open for its date.

The settlement is posted the way the assistant's own entries are (marked ``AI_POSTED`` so it is found and checked), with the
bill allocated in the same step. Anything less certain stays where it was: the row is offered with the bill proposed when a
person settles it (``ledger.settlement``), and a payment already posted to some other head is shown beside the invoice.
"""

from __future__ import annotations

import datetime
import logging
import re

from django.db import DatabaseError, transaction
from django.db.models import BigIntegerField, F, Sum, Value
from django.db.models.functions import Coalesce

from banking.models import StatementTransaction
from classify.models import ClassificationMethod, PartyAlias
from ledger import approval, billing
from ledger.models import Bill, BillKind

logger = logging.getLogger("autoca.matching")

#: A payment may precede its invoice (an advance) by this long, and follow it by this long.
DAYS_BEFORE = 30
DAYS_AFTER = 150


def _squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", (text or "").upper()).strip()


def _names_of(party) -> list[str]:
    names = [party.canonical_name]
    names += [a.alias_display for a in PartyAlias.objects.filter(firm_id=party.firm_id, party=party)]
    return [n for n in (_squash(n) for n in names) if len(n) >= 4]


def _says(narration: str, names: list[str]) -> bool:
    text = f" {_squash(narration)} "
    return any(f" {n} " in text for n in names)


#: What a customer may deduct under each section, in basis points of the taxable value (the rate depends on who is paid, so
#: every usual rate is tried). TDS is deducted to the nearest rupee.
TDS_RATES_BP = {"194C": (100, 200), "194H": (500,), "194I": (1000, 200), "194J": (1000, 200), "194Q": (10,), "194A": (1000,)}


def _tds_options(bill: Bill) -> list[int]:
    """The TDS amounts (paise) a customer could have deducted from this whole, unpaid sales bill."""
    if bill.kind != BillKind.SALES or not bill.party.tds_section or _open_amount(bill) != bill.total_paise:
        return []
    out = []
    for bp in TDS_RATES_BP.get(bill.party.tds_section, ()):
        rupees = (bill.taxable_paise * bp // 10_000 + 50) // 100
        tds = rupees * 100
        if 0 < tds < bill.total_paise and tds not in out:
            out.append(tds)
    return out


def _field(bill: Bill) -> str:
    """The statement column a bill's payment sits in: money out pays a purchase, money in pays a sale."""
    return "debit_paise" if bill.kind == BillKind.PURCHASE else "credit_paise"


def _open_amount(bill: Bill) -> int:
    return bill.open_paise if hasattr(bill, "open_paise") else billing.open_amount(bill)


def _rows_for(bill: Bill, names: list[str]) -> list[tuple[StatementTransaction, int]]:
    """Unposted bank rows that could be this bill's payment, with the TDS each implies (0 when it is paid in full).

    By amount, date and evidence of whose they are.
    """
    amount = _open_amount(bill)
    if amount <= 0 or bill.kind not in (BillKind.PURCHASE, BillKind.SALES):
        return []
    amounts = {amount: 0}
    for tds in _tds_options(bill):
        amounts.setdefault(amount - tds, tds)
    rows = (
        StatementTransaction.objects.filter(
            firm_id=bill.firm_id,
            bank_account__client_id=bill.client_id,
            value_date__gte=bill.bill_date - datetime.timedelta(days=DAYS_BEFORE),
            value_date__lte=bill.bill_date + datetime.timedelta(days=DAYS_AFTER),
            **{f"{_field(bill)}__in": list(amounts)},
        )
        .select_related("classification", "bank_account")
        .prefetch_related("journal_entries")
    )
    found = []
    for row in rows:
        classification = getattr(row, "classification", None)
        if classification is None or approval._live_entry_for(row) is not None:
            continue
        if classification.method == ClassificationMethod.REVIEWED:
            continue  # a person has already decided what this row is
        if classification.party_id == bill.party_id or _says(row.narration, names):
            found.append((row, amounts[getattr(row, _field(bill))]))
    return found


def _open_bills(client) -> list[Bill]:
    """The client's purchase and sales bills with something still owing, each carrying ``open_paise``, in one query."""
    return list(
        Bill.objects.filter(firm_id=client.firm_id, client=client, kind__in=(BillKind.PURCHASE, BillKind.SALES))
        .select_related("party")
        .annotate(settled=Coalesce(Sum("allocations__amount_paise"), Value(0), output_field=BigIntegerField()))
        .annotate(open_paise=F("total_paise") - F("settled"))
        .filter(open_paise__gt=0)
    )


def match_client(client) -> int:
    """Settle every unambiguous bill/row pair for this client. Returns how many were settled."""
    bills = _open_bills(client)
    names = {b.party_id: _names_of(b.party) for b in bills}
    by_bill = {b.pk: _rows_for(b, names[b.party_id]) for b in bills}

    claims: dict = {}
    for bill in bills:
        for row, _ in by_bill[bill.pk]:
            claims.setdefault(row.pk, []).append(bill.pk)

    settled = 0
    for bill in bills:
        rows = by_bill[bill.pk]
        if len(rows) != 1 or len(claims[rows[0][0].pk]) != 1:
            continue  # nothing matches, or it is not the only candidate on one side
        if _settle(bill, *rows[0]):
            settled += 1
    return settled


def rematch(client) -> int:
    """Look again for certain pairs after something a person did may have made one: a spelling confirmed, a row's party set,
    a party created or changed, a bill revised.

    Best effort and silent: it runs after the person's own action has succeeded, so whatever goes wrong here is logged and
    left, never turned into a failure of that action. Returns how many pairs were settled.
    """
    try:
        with transaction.atomic():
            return match_client(client)
    except (DatabaseError, billing.BillingError, approval.NotApprovableError):
        logger.warning("re-matching bills and bank rows for client %s failed; left for the next run", client.pk, exc_info=True)
        return 0


def match_bill(bill: Bill) -> bool:
    """Settle this one bill if its payment is certain. Also refuses when another open bill could be the same payment."""
    names = _names_of(bill.party)
    rows = _rows_for(bill, names)
    if len(rows) != 1:
        return False
    row, tds = rows[0]
    for other in _open_bills(bill.client):
        if other.pk != bill.pk and any(r.pk == row.pk for r, _ in _rows_for(other, _names_of(other.party))):
            return False
    return _settle(bill, row, tds)


def _settle(bill: Bill, row: StatementTransaction, tds: int = 0) -> bool:
    try:
        with transaction.atomic():
            return approval.auto_post_settlement(row.classification, bill, tds_paise=tds) is not None
    except (billing.BillingError, approval.NotApprovableError):
        return False
