"""Posting an entry straight into the journal, for tests about what the reports make of it."""

from __future__ import annotations

import itertools

from django.utils import timezone

from classify.models import LedgerAccount
from core.fy import financial_year
from ledger.models import Direction, JournalEntry, JournalLine, VoucherType

_numbers = itertools.count(1)


def make_ledger(client, name, group) -> LedgerAccount:
    return LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name=name, defaults={"group": group}
    )[0]


def post(client, date, debit, credit, paise) -> JournalEntry:
    """One balanced two-line entry. Call inside ``firm_context``."""
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=next(_numbers),
        financial_year=financial_year(date),
        entry_date=date,
        voucher_type=VoucherType.JOURNAL,
        approved_at=timezone.now(),
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine.build(entry=entry, ledger_account=debit, direction=Direction.DEBIT, amount_paise=paise),
            JournalLine.build(entry=entry, ledger_account=credit, direction=Direction.CREDIT, amount_paise=paise),
        ]
    )
    return entry
