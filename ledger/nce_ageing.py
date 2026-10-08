"""How old the money customers owe is, as at a year end, for Note 16 (Trade receivables).

The format asks two things of a receivable: whether it has been outstanding for more than six months *from the date it was
due for receipt*, and whether it is good or doubtful. Age is counted from the bill's due date, or its own date when it has
none, to the 31 March in question -- not to today -- and a bill counts as settled only by what was allocated to it by then.
Whatever the bills do not account for (a receipt on account, a credit note, a balance with no bill behind it) is reported as
its own row, so the schedule always adds up to the line on the Balance Sheet.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from ledger.models import Bill, Direction


def add_months(day: datetime.date, months: int) -> datetime.date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return datetime.date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def is_over_six_months(due: datetime.date | None, bill_date: datetime.date, as_at: datetime.date) -> bool:
    """Whether the money has been outstanding for more than six months from the day it was due."""
    return add_months(due or bill_date, 6) < as_at


def split_by_age(items: Iterable[tuple[datetime.date | None, datetime.date, int]], as_at: datetime.date) -> tuple[int, int]:
    """``(under six months, over six months)`` from ``(due date, bill date, amount outstanding)``."""
    under = over = 0
    for due, billed, amount in items:
        if amount <= 0:
            continue
        if is_over_six_months(due, billed, as_at):
            over += amount
        else:
            under += amount
    return under, over


def outstanding_bills(client, ledger_ids, as_at: datetime.date) -> list[tuple[datetime.date | None, datetime.date, int]]:
    """Sales bills on these customer ledgers that were still open on ``as_at``, with what was left of each."""
    if not ledger_ids:
        return []
    bills = (
        Bill.objects.filter(
            firm_id=client.firm_id,
            client=client,
            direction=Direction.DEBIT,
            booked_on__lte=as_at,
            party__ledger_id__in=ledger_ids,
        )
        .annotate(settled=Coalesce(Sum("allocations__amount_paise", filter=Q(allocations__line__entry__entry_date__lte=as_at)), 0))
        .values_list("due_date", "bill_date", "total_paise", "settled")
    )
    return [(due, billed, total - settled) for due, billed, total, settled in bills]
