"""Tax deducted at source: what the client deducted, what it paid in, and what is late.

Everything is read from the journal, so it cannot disagree with the books. A deduction is a credit on the ``TDS Payable``
ledger carrying its section (a purchase that deducted TDS posts it there); a deposit is a debit on the same ledger (the bank
payment to the tax department). A deposit becomes a *challan* once someone records its BSR code and serial number
(``TdsChallan``), which is what the quarterly return needs.

TDS deducted in a month is due by the 7th of the next month, and for March by 30 April. A deposit is matched to the oldest
unpaid deduction of its section first. A payment to ``TDS Payable`` with no challan recorded, and a deduction past its due
date with nothing deposited against it, are open items.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum

from classify.models import LedgerAccount
from core.access import require_posting_rights
from core.rbac import require_permission
from ledger.billing import TDS_PAYABLE
from ledger.models import Direction, EntryKind, JournalEntry, JournalLine, TdsChallan

BSR = re.compile(r"^\d{7}$")
SERIAL = re.compile(r"^\d{5}$")
UNSPECIFIED = "?"


class TdsError(ValueError):
    """The challan cannot be recorded. The message says what to change."""


def payable_ledger(client) -> LedgerAccount | None:
    return LedgerAccount.objects.filter(firm_id=client.firm_id, client=client, name=TDS_PAYABLE).first()


def due_date(year: int, month: int) -> datetime.date:
    """When TDS deducted in this month must be deposited: the 7th of the next, and 30 April for March."""
    if month == 3:
        return datetime.date(year, 4, 30)
    nxt = month + 1
    return datetime.date(year + (1 if nxt > 12 else 0), nxt - 12 if nxt > 12 else nxt, 7)


def quarter_of(month: int) -> int:
    """Financial-year quarter: April to June is 1, up to January to March, 4."""
    return ((month - 4) % 12) // 3 + 1


@dataclass
class Month:
    section: str
    year: int
    month: int
    deducted_paise: int = 0
    deposited_paise: int = 0

    @property
    def due(self) -> datetime.date:
        return due_date(self.year, self.month)

    @property
    def unpaid_paise(self) -> int:
        return max(self.deducted_paise - self.deposited_paise, 0)

    @property
    def quarter(self) -> int:
        return quarter_of(self.month)

    @property
    def financial_year(self) -> int:
        return self.year if self.month >= 4 else self.year - 1


def position(client) -> list[Month]:
    """Each section's deductions by month, with the deposits for that section matched oldest first."""
    ledger = payable_ledger(client)
    if ledger is None:
        return []
    lines = JournalLine.objects.filter(firm_id=client.firm_id, ledger_account=ledger).select_related("entry")
    by_key: dict[tuple, Month] = {}
    for line in lines.filter(direction=Direction.CREDIT):
        section = line.tds_section or UNSPECIFIED
        day = line.entry.entry_date
        month = by_key.setdefault((section, day.year, day.month), Month(section, day.year, day.month))
        month.deducted_paise += line.amount_paise

    paid: dict[str, int] = {}
    for challan in TdsChallan.objects.filter(firm_id=client.firm_id, client=client).select_related("entry"):
        amount = (
            JournalLine.objects.filter(entry=challan.entry, ledger_account=ledger, direction=Direction.DEBIT).aggregate(
                total=Sum("amount_paise")
            )["total"]
            or 0
        )
        paid[challan.section] = paid.get(challan.section, 0) + amount

    months = sorted(by_key.values(), key=lambda m: (m.section, m.year, m.month))
    for section in {m.section for m in months}:
        left = paid.get(section, 0)
        for month in (m for m in months if m.section == section):
            take = min(left, month.deducted_paise)
            month.deposited_paise = take
            left -= take
    return months


def payments_without_challan(client) -> list[tuple[JournalEntry, int]]:
    """Bank payments debited to TDS Payable that have no challan recorded: money paid in that cannot be reported yet."""
    ledger = payable_ledger(client)
    if ledger is None:
        return []
    out = []
    lines = (
        JournalLine.objects.filter(firm_id=client.firm_id, ledger_account=ledger, direction=Direction.DEBIT)
        .select_related("entry")
        .order_by("entry__entry_date")
    )
    for line in lines:
        if not TdsChallan.objects.filter(entry_id=line.entry_id).exists():
            out.append((line.entry, line.amount_paise))
    return out


@transaction.atomic
def record_challan(
    client, entry: JournalEntry, *, section: str, bsr_code: str, serial: str, paid_on: datetime.date, membership
) -> TdsChallan:
    """Say which section a payment to the tax department was for, and its challan number (BSR code and serial)."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    section = (section or "").strip().upper()
    if not section:
        raise TdsError("Say which section this challan is for, like 194C.")
    if not BSR.match(bsr_code or ""):
        raise TdsError("The BSR code is seven digits.")
    if not SERIAL.match(serial or ""):
        raise TdsError("The challan serial number is five digits.")
    if entry.client_id != client.pk or entry.firm_id != client.firm_id:
        raise TdsError("That payment belongs to a different client.")
    if entry.entry_kind != EntryKind.BANK:
        raise TdsError("A challan is recorded against a bank payment.")
    ledger = payable_ledger(client)
    debit = (
        JournalLine.objects.filter(entry=entry, ledger_account=ledger, direction=Direction.DEBIT).first() if ledger else None
    )
    if debit is None:
        raise TdsError("That payment is not booked to TDS Payable, so it is not a TDS deposit.")
    if TdsChallan.objects.filter(entry=entry).exists():
        raise TdsError("A challan is already recorded for that payment.")
    return TdsChallan.objects.create(
        firm_id=client.firm_id, client=client, entry=entry, section=section, bsr_code=bsr_code, serial=serial, paid_on=paid_on
    )


@transaction.atomic
def remove_challan(challan: TdsChallan, *, membership) -> None:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, challan.client)
    challan.delete()
