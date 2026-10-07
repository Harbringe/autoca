"""Helpers for the work-count dashboards: entries with a chosen approver and time, and who is assigned to what."""

from __future__ import annotations

import datetime
import itertools

from django.utils import timezone

from classify.models import LedgerGroup
from core.db.session import firm_context
from core.fy import financial_year
from core.models import Client, ClientAssignment, FirmMembership
from ledger.models import Direction, JournalEntry, JournalLine, VoucherType
from ledger.tests.support import make_ledger

_numbers = itertools.count(9000)


def aware(year, month, day, hour=11) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime(year, month, day, hour, 0))


def post_entry(
    client, *, by=None, at=None, on=datetime.date(2025, 5, 10), corrects=None
) -> JournalEntry:
    """One balanced entry on ``client``. ``by`` is a membership, or None for an entry the assistant posted."""
    with firm_context(client.firm_id):
        cash = make_ledger(client, "WS Cash", LedgerGroup.CASH)
        sales = make_ledger(client, "WS Sales", LedgerGroup.DIRECT_INCOME)
        entry = JournalEntry.objects.create(
            firm_id=client.firm_id,
            client=client,
            entry_no=next(_numbers),
            financial_year=financial_year(on),
            entry_date=on,
            voucher_type=VoucherType.JOURNAL,
            approved_by=by.user if by is not None else None,
            approved_at=at or timezone.now(),
            supersedes=corrects,
        )
        JournalLine.objects.bulk_create(
            [
                JournalLine.build(
                    entry=entry, ledger_account=cash, direction=Direction.DEBIT, amount_paise=100_00
                ),
                JournalLine.build(
                    entry=entry,
                    ledger_account=sales,
                    direction=Direction.CREDIT,
                    amount_paise=100_00,
                ),
            ]
        )
    return entry


def scoped(membership, *, manager=None) -> FirmMembership:
    """Take away 'sees every client', optionally putting the member on a manager's team."""
    with firm_context(membership.firm_id):
        FirmMembership.objects.filter(pk=membership.pk).update(
            scope_all_clients=False, manager=manager
        )
        membership.refresh_from_db()
    return membership


def assign(client, membership) -> None:
    with firm_context(client.firm_id):
        ClientAssignment.objects.create(
            firm_id=client.firm_id, client=client, membership=membership
        )


def lead(client, membership) -> None:
    with firm_context(client.firm_id):
        Client.objects.filter(pk=client.pk).update(lead=membership)
