"""What a client owes, what it is owed, and a party's account: the reports a CA actually hands over.

Both are read from the same bills and allocations that ``billing.party_position`` checks against the ledger, so neither can
drift from the books: if a party's ledger and its bills disagree, that is an open item, not a quietly different report.

**Outstanding** is every bill still owing on a date, by party, aged from the bill date: "what do we owe Ravi Traders, and how
old is it". It is worked out *as at any date*, counting only the settlements that had happened by then, so last month's
report stays what it was. A debit or credit note shows as a negative against the bills it reverses, and money held on account
or as an advance shows as a negative against the party, so the party's total is what is truly owed.

**Statement of account** is one party's ledger, line by line, with a running balance: what the party would be sent.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.db.models import BigIntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce

from classify.models import LedgerGroup, Party
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    Direction,
    JournalLine,
    LedgerOpening,
)

PAYABLES = "payables"
RECEIVABLES = "receivables"

#: Ageing buckets, in days from the bill date to the report date: ``(label, from, to)``, ``to`` open-ended for the last.
BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("Over 90", 91, None),
)
BUCKET_LABELS = tuple(label for label, _, _ in BUCKETS)

_SIDES = {
    PAYABLES: {
        "kinds": (BillKind.PURCHASE, BillKind.DEBIT_NOTE),
        "group": LedgerGroup.CREDITOR,
        "natural": Direction.CREDIT,
    },
    RECEIVABLES: {
        "kinds": (BillKind.SALES, BillKind.CREDIT_NOTE),
        "group": LedgerGroup.DEBTOR,
        "natural": Direction.DEBIT,
    },
}


def bucket_for(age_days: int) -> str:
    """The ageing bucket for a bill this many days old. A bill dated after the report date is not in the report."""
    for label, low, high in BUCKETS:
        if age_days >= low and (high is None or age_days <= high):
            return label
    return BUCKET_LABELS[0]


@dataclass(frozen=True)
class OutstandingBill:
    bill: Bill
    #: What is still owing on this bill on the report date, signed for the side: a note that reverses a bill is negative.
    open_paise: int
    age_days: int
    bucket: str


@dataclass
class PartyOutstanding:
    party: object
    bills: list[OutstandingBill] = field(default_factory=list)
    #: Money paid or received with no bill named, as a negative: it reduces what is owed.
    on_account_paise: int = 0

    @property
    def bills_paise(self) -> int:
        return sum(item.open_paise for item in self.bills)

    @property
    def total_paise(self) -> int:
        return self.bills_paise + self.on_account_paise

    def bucket_paise(self, label: str) -> int:
        return sum(item.open_paise for item in self.bills if item.bucket == label)


@dataclass
class Outstanding:
    side: str
    as_of: datetime.date
    parties: list[PartyOutstanding]

    @property
    def total_paise(self) -> int:
        return sum(p.total_paise for p in self.parties)

    @property
    def on_account_paise(self) -> int:
        return sum(p.on_account_paise for p in self.parties)

    def bucket_paise(self, label: str) -> int:
        return sum(p.bucket_paise(label) for p in self.parties)


def outstanding(client, as_of: datetime.date, side: str) -> Outstanding:
    """Every bill still owing for ``client`` on ``as_of``, on one side, by party, aged from the bill date."""
    if side not in _SIDES:
        raise ValueError(f"side must be {PAYABLES!r} or {RECEIVABLES!r}, not {side!r}")
    rules = _SIDES[side]

    bills = (
        Bill.objects.filter(firm_id=client.firm_id, client=client, bill_date__lte=as_of)
        .filter(Q(kind__in=rules["kinds"]) | Q(kind=BillKind.OPENING, party__ledger__group=rules["group"]))
        .select_related("party")
        .annotate(
            settled=Coalesce(
                Sum("allocations__amount_paise", filter=Q(allocations__line__entry__entry_date__lte=as_of)),
                Value(0),
                output_field=BigIntegerField(),
            )
        )
        .order_by("bill_date", "reference")
    )

    by_party: dict = {}
    for bill in bills:
        remaining = bill.total_paise - bill.settled
        if remaining == 0:
            continue
        sign = 1 if bill.direction == rules["natural"] else -1
        age = (as_of - bill.bill_date).days
        entry = by_party.setdefault(bill.party_id, PartyOutstanding(party=bill.party))
        entry.bills.append(OutstandingBill(bill=bill, open_paise=sign * remaining, age_days=age, bucket=bucket_for(age)))

    held = (
        BillAllocation.objects.filter(
            firm_id=client.firm_id,
            client=client,
            kind__in=[AllocationKind.ON_ACCOUNT, AllocationKind.ADVANCE],
            line__entry__entry_date__lte=as_of,
            line__ledger_account__group=rules["group"],
        )
        .values("line__party_id")
        .annotate(total=Sum("amount_paise"))
    )
    for row in held:
        party_id = row["line__party_id"]
        if party_id is None:
            continue
        entry = by_party.get(party_id)
        if entry is None:
            # Money held for a party that has no open bill: it still reduces what is owed, so the party is listed.
            entry = by_party[party_id] = PartyOutstanding(party=Party.objects.get(pk=party_id))
        entry.on_account_paise = -row["total"]

    ordered = sorted(by_party.values(), key=lambda p: p.party.canonical_name.lower())
    return Outstanding(side=side, as_of=as_of, parties=ordered)


# ---------------------------------------------------------------------------
# A party's statement of account
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatementRow:
    date: datetime.date
    voucher_type: str
    entry_no: int
    narration: str
    debit_paise: int
    credit_paise: int
    #: Debits positive, like the ledger: a supplier the client owes is negative.
    balance_paise: int
    entry_id: object
    bill_id: object | None


@dataclass
class Statement:
    party: object
    date_from: datetime.date
    date_to: datetime.date
    opening_paise: int
    rows: list[StatementRow]

    @property
    def closing_paise(self) -> int:
        return self.rows[-1].balance_paise if self.rows else self.opening_paise

    @property
    def total_debit_paise(self) -> int:
        return sum(r.debit_paise for r in self.rows)

    @property
    def total_credit_paise(self) -> int:
        return sum(r.credit_paise for r in self.rows)


def party_statement(party, date_from: datetime.date, date_to: datetime.date) -> Statement:
    """The party's own ledger from ``date_from`` to ``date_to``: what to send them.

    The opening balance is the ledger's imported opening plus everything posted before ``date_from``, which is exactly what
    ``party_position`` compares with the bills, so the statement and the control check cannot disagree.
    """
    if not party.ledger_id:
        return Statement(party=party, date_from=date_from, date_to=date_to, opening_paise=0, rows=[])

    ledger = party.ledger
    opening_row = LedgerOpening.objects.filter(firm_id=party.firm_id, ledger=ledger).order_by("financial_year").first()
    before = (
        JournalLine.objects.filter(firm_id=party.firm_id, ledger_account=ledger, entry__entry_date__lt=date_from)
        .aggregate(total=Sum("signed_paise"))["total"]
        or 0
    )
    balance = (opening_row.signed_paise if opening_row else 0) + before

    lines = (
        JournalLine.objects.filter(
            firm_id=party.firm_id, ledger_account=ledger, entry__entry_date__gte=date_from, entry__entry_date__lte=date_to
        )
        .select_related("entry", "entry__bill")
        .order_by("entry__entry_date", "entry__voucher_type", "entry__entry_no", "created_at")
    )

    opening = balance
    rows: list[StatementRow] = []
    for line in lines:
        balance += line.signed_paise
        entry = line.entry
        bill = getattr(entry, "bill", None)
        rows.append(
            StatementRow(
                date=entry.entry_date,
                voucher_type=entry.voucher_type,
                entry_no=entry.entry_no,
                narration=entry.narration,
                debit_paise=line.amount_paise if line.direction == Direction.DEBIT else 0,
                credit_paise=line.amount_paise if line.direction == Direction.CREDIT else 0,
                balance_paise=balance,
                entry_id=entry.pk,
                bill_id=bill.pk if bill else None,
            )
        )
    return Statement(party=party, date_from=date_from, date_to=date_to, opening_paise=opening, rows=rows)
