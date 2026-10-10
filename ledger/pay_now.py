"""Paid when booked: a cash purchase or a cash sale, booked with its payment in one go.

A bill is normally settled later, by a bank row a person matches to it. A purchase paid from the till has no bank row at all,
so the payment would otherwise never be booked and the supplier would sit owed. ``pay_now`` books the payment voucher (Dr the
party, Cr the cash or bank ledger for a purchase; the other way for a sale) and settles the bill against it.

A bank account whose statements are uploaded is refused: that payment is on the statement and will be booked from it, so
booking it here too would count it twice.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from banking.models import BankAccount
from classify.models import LedgerAccount, LedgerGroup, LedgerStatus
from core.access import require_posting_rights
from core.fy import financial_year
from core.rbac import require_permission
from ledger import approval, billing
from ledger.billing import BillingError
from ledger.models import (
    Bill,
    BillKind,
    Direction,
    EntryKind,
    JournalEntry,
    JournalLine,
    VoucherType,
)

PAYABLE_FROM = (LedgerGroup.CASH, LedgerGroup.BANK)


@transaction.atomic
def pay_now(bill: Bill, from_ledger: LedgerAccount, *, membership, on: datetime.date | None = None) -> JournalEntry:
    """Book the payment of the whole of ``bill`` from ``from_ledger`` (cash, or a bank ledger with no uploaded statements)."""
    require_permission(membership, "journal.approve")
    client = bill.client
    require_posting_rights(membership, client)
    if bill.kind not in (BillKind.PURCHASE, BillKind.SALES):
        raise BillingError("Only a purchase or a sale is paid when booked.")
    if from_ledger.client_id != client.pk or from_ledger.firm_id != client.firm_id:
        raise BillingError("That account belongs to a different client.")
    if from_ledger.group not in PAYABLE_FROM or from_ledger.status != LedgerStatus.ACTIVE:
        raise BillingError(f"{from_ledger.name!r} is not a cash or bank account in use.")
    if BankAccount.objects.filter(client=client, ledger_name=from_ledger.name).exists():
        raise BillingError(
            f"{from_ledger.name!r} has bank statements uploaded, so this payment will be booked from its statement. "
            f"Leave 'paid from' empty and match the payment there."
        )
    owed = billing.open_amount(bill)
    if owed <= 0:
        raise BillingError("Nothing is left to pay on this bill.")
    day = on or bill.bill_date
    from ledger import editing

    through = editing.locked_through(client.pk)
    if through is not None and day <= through:
        raise BillingError(f"The books are signed off through {through:%d-%m-%Y}; date the payment after that.")

    purchase = bill.kind == BillKind.PURCHASE
    voucher_type = VoucherType.PAYMENT if purchase else VoucherType.RECEIPT
    year = financial_year(day)
    party_ledger = billing.party_ledger_for(bill.party)
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=approval.allocate_voucher_number(client, year, voucher_type),
        financial_year=year,
        entry_date=day,
        voucher_type=voucher_type,
        entry_kind=EntryKind.VOUCHER,
        narration=f"Being {bill.reference} of {bill.party.canonical_name} {'paid' if purchase else 'received'} through {from_ledger.name}",
        approved_by=membership.user,
        approved_at=timezone.now(),
    )
    party_direction = Direction.DEBIT if purchase else Direction.CREDIT
    source_direction = Direction.CREDIT if purchase else Direction.DEBIT
    lines = [
        JournalLine.build(entry=entry, ledger_account=party_ledger, party=bill.party, direction=party_direction, amount_paise=owed),
        JournalLine.build(entry=entry, ledger_account=from_ledger, direction=source_direction, amount_paise=owed),
    ]
    JournalLine.objects.bulk_create(lines)
    billing.allocate(lines[0], bill=bill, amount_paise=owed)
    return entry
