"""Party accounting: invoices as bills, parties as ledgers, payments settling bills.

Until now a supplier's invoice had nowhere to go in the books: a payment to the supplier was posted straight to an
expense head, so there was no balance owed, no input tax, and no way to say what a customer still owes. This module is
that missing half. See ``docs/design/party-accounting-phase1.md``.

Two halves, kept apart on purpose.

**The planner** (``plan_purchase``, ``plan_sales``, ``plan_debit_note``, ``plan_credit_note``) is pure arithmetic: invoice
figures in, debit and credit lines out. It touches no database, so the rules that decide where a rupee goes -- GST, reverse
charge, TDS, rounding -- are tested without one, and every plan balances by construction.

**The posting layer** (``post_purchase`` and the rest) turns a plan into a voucher, a bill and its journal lines, under the
same permission, sign-off lock and numbering as a bank entry. The database then enforces the rest (see ``ledger/0012``).

What links this to everything else is the bill's ``invoice_key``: the same identity the GST module uses, so a bill, an
uploaded register row and a GSTR-2B row are one invoice. A bill with no uploaded document is allowed, and is reported as an
open item rather than accepted silently.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from classify.models import (
    CRYPTO_PURPOSE,
    LedgerAccount,
    LedgerGroup,
    LedgerStatus,
    Party,
    PartyRole,
)
from classify.standard_ledgers import STANDARD_LEDGERS
from core.access import require_posting_rights
from core.crypto import blind_index
from core.fy import financial_year
from core.identity import invoice_key, normalise_gstin, supplier_identity
from core.rbac import require_permission
from ledger import approval, editing
from ledger.models import (
    AllocationKind,
    Bill,
    BillAllocation,
    BillKind,
    ChangeAction,
    Direction,
    EntryKind,
    JournalEntry,
    JournalLine,
    LedgerOpening,
    VoucherType,
)

DR, CR = Direction.DEBIT, Direction.CREDIT

#: The standard ledgers a voucher posts to. Created for a client the first time one is needed.
INPUT = {"cgst": "Input CGST", "sgst": "Input SGST", "igst": "Input IGST", "cess": "Input Cess"}
OUTPUT = {"cgst": "Output CGST", "sgst": "Output SGST", "igst": "Output IGST", "cess": "Output Cess"}
INPUT_RCM = "Input GST (RCM)"
PAYABLE_RCM = "GST Payable (RCM)"
TDS_PAYABLE = "TDS Payable"
ROUND_OFF = "Round Off"

#: Stands for the party's own ledger in a plan; resolved when the voucher is posted.
PARTY = "<party>"

#: Heads an invoice may never post to: the money side of a purchase or sale is the party, not a bank or the cash box.
_NOT_A_HEAD = {LedgerGroup.BANK, LedgerGroup.CASH, LedgerGroup.BANK_OD, LedgerGroup.CREDITOR, LedgerGroup.DEBTOR}


class BillingError(ValueError):
    """The voucher cannot be booked as asked. Always something a person can fix."""


# ---------------------------------------------------------------------------
# The planner: pure arithmetic, no database
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedLine:
    """One side of a planned voucher. ``ledger`` is a ledger, a standard ledger's name, or ``PARTY``."""

    ledger: object
    direction: str
    amount_paise: int
    rcm: bool = False
    tds_section: str = ""


@dataclass(frozen=True)
class VoucherPlan:
    lines: tuple[PlannedLine, ...]
    #: What the party's ledger is debited or credited for. Becomes the bill's total.
    party_paise: int
    #: Taxable value, before any tax.
    taxable_paise: int

    @property
    def debits(self) -> int:
        return sum(line.amount_paise for line in self.lines if line.direction == DR)

    @property
    def credits(self) -> int:
        return sum(line.amount_paise for line in self.lines if line.direction == CR)


def _check_heads(heads) -> int:
    if not heads:
        raise BillingError("An invoice needs at least one head with an amount.")
    for _, amount in heads:
        if not isinstance(amount, int) or amount <= 0:
            raise BillingError("Every head on an invoice needs an amount above zero, in whole paise.")
    return sum(amount for _, amount in heads)


def _check_tax(cgst: int, sgst: int, igst: int, cess: int) -> int:
    for name, amount in (("CGST", cgst), ("SGST", sgst), ("IGST", igst), ("Cess", cess)):
        if not isinstance(amount, int) or amount < 0:
            raise BillingError(f"{name} must be a whole number of paise, zero or more.")
    if igst and (cgst or sgst):
        raise BillingError("An invoice carries CGST and SGST, or IGST, not both.")
    return cgst + sgst + igst + cess


def plan_purchase(
    heads, *, cgst=0, sgst=0, igst=0, cess=0, round_off=0, tds=0, rcm=False, tds_section=""
) -> VoucherPlan:
    """A supplier's invoice.

    ``heads`` is ``[(ledger, taxable_paise), ...]``: the expense, purchase or asset heads the goods or service go to.

    Under reverse charge the client, not the supplier, owes the GST, so the party is credited only the taxable value and
    the tax is booked against itself: ``Dr Input GST (RCM) / Cr GST Payable (RCM)``. That nets to nothing in the books
    and is picked up in the return. TDS is deducted at booking: the party is credited the net, and ``TDS Payable`` the
    deduction. ``round_off`` is signed, positive when the invoice rounds up.
    """
    taxable = _check_heads(heads)
    tax = _check_tax(cgst, sgst, igst, cess)
    if not isinstance(tds, int) or tds < 0 or not isinstance(round_off, int):
        raise BillingError("TDS must be a whole number of paise, zero or more, and the round-off whole paise.")
    party_paise = taxable + (0 if rcm else tax) + round_off - tds
    if party_paise <= 0:
        raise BillingError("After tax, rounding and TDS the supplier would be owed nothing. Check the amounts.")

    lines = [PlannedLine(ledger, DR, amount) for ledger, amount in heads]
    if tax and rcm:
        lines += [PlannedLine(INPUT_RCM, DR, tax, rcm=True), PlannedLine(PAYABLE_RCM, CR, tax, rcm=True)]
    elif tax:
        lines += [
            PlannedLine(INPUT[key], DR, amount)
            for key, amount in (("cgst", cgst), ("sgst", sgst), ("igst", igst), ("cess", cess))
            if amount
        ]
    if round_off > 0:
        lines.append(PlannedLine(ROUND_OFF, DR, round_off))
    elif round_off < 0:
        lines.append(PlannedLine(ROUND_OFF, CR, -round_off))
    lines.append(PlannedLine(PARTY, CR, party_paise))
    if tds:
        lines.append(PlannedLine(TDS_PAYABLE, CR, tds, tds_section=tds_section))
    return _balanced(lines, party_paise, taxable)


def plan_sales(heads, *, cgst=0, sgst=0, igst=0, cess=0, round_off=0) -> VoucherPlan:
    """Our invoice to a customer: ``Dr Customer / Cr Sales / Cr Output GST``, rounding either side."""
    taxable = _check_heads(heads)
    tax = _check_tax(cgst, sgst, igst, cess)
    if not isinstance(round_off, int):
        raise BillingError("The round-off must be whole paise.")
    party_paise = taxable + tax + round_off
    if party_paise <= 0:
        raise BillingError("After tax and rounding the customer would owe nothing. Check the amounts.")

    lines = [PlannedLine(PARTY, DR, party_paise)]
    lines += [PlannedLine(ledger, CR, amount) for ledger, amount in heads]
    lines += [
        PlannedLine(OUTPUT[key], CR, amount)
        for key, amount in (("cgst", cgst), ("sgst", sgst), ("igst", igst), ("cess", cess))
        if amount
    ]
    if round_off > 0:
        lines.append(PlannedLine(ROUND_OFF, CR, round_off))
    elif round_off < 0:
        lines.append(PlannedLine(ROUND_OFF, DR, -round_off))
    return _balanced(lines, party_paise, taxable)


def _flip(plan: VoucherPlan) -> VoucherPlan:
    return VoucherPlan(
        lines=tuple(
            PlannedLine(
                planned.ledger, CR if planned.direction == DR else DR, planned.amount_paise, planned.rcm, planned.tds_section
            )
            for planned in plan.lines
        ),
        party_paise=plan.party_paise,
        taxable_paise=plan.taxable_paise,
    )


def plan_debit_note(heads, **tax) -> VoucherPlan:
    """A purchase return: the invoice the other way round. ``Dr Supplier / Cr Purchases / Cr Input GST``."""
    if tax.get("tds") or tax.get("rcm"):
        raise BillingError("A debit note does not deduct TDS or carry reverse charge in this version.")
    return _flip(plan_purchase(heads, **tax))


def plan_credit_note(heads, **tax) -> VoucherPlan:
    """A sales return: ``Dr Sales / Dr Output GST / Cr Customer``."""
    return _flip(plan_sales(heads, **tax))


def _balanced(lines, party_paise: int, taxable: int) -> VoucherPlan:
    plan = VoucherPlan(lines=tuple(lines), party_paise=party_paise, taxable_paise=taxable)
    if plan.debits != plan.credits:  # pragma: no cover - a bug in this module, never a user error
        raise BillingError(f"Internal error: the voucher does not balance ({plan.debits} against {plan.credits}).")
    return plan


# ---------------------------------------------------------------------------
# Party ledgers
# ---------------------------------------------------------------------------


def standard_ledger(client, name: str) -> LedgerAccount:
    """A standard ledger of the client's, opened the first time it is needed."""
    groups = dict(STANDARD_LEDGERS)
    if name not in groups:
        raise BillingError(f"{name!r} is not a standard ledger.")
    ledger, _ = LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name=name, defaults={"group": groups[name]}
    )
    if ledger.status != LedgerStatus.ACTIVE:
        raise BillingError(f"The ledger {name!r} is not in use. Accept or restore it before booking vouchers.")
    return ledger


def party_ledger_for(party: Party, *, side: str | None = None) -> LedgerAccount:
    """The party's own account in the books, opened the first time it is used.

    A supplier's is under Sundry Creditors and a customer's under Sundry Debtors. A party that is both takes the side it
    is first used on (``side``). A ledger of the same name that the client already has in one of those groups and that
    no other party owns -- typically one imported from Tally -- is adopted rather than duplicated, so imported history and
    new vouchers share one account.
    """
    if party.ledger_id:
        return party.ledger

    if side is None:
        side = LedgerGroup.DEBTOR if party.role == PartyRole.CUSTOMER else LedgerGroup.CREDITOR
    name = " ".join(party.canonical_name.split())
    ledgers = LedgerAccount.objects.filter(firm_id=party.firm_id, client_id=party.client_id)

    existing = ledgers.filter(name=name).first()
    if existing is not None:
        adoptable = (
            existing.group in (LedgerGroup.CREDITOR, LedgerGroup.DEBTOR)
            and not Party.objects.filter(ledger=existing).exists()
        )
        if adoptable:
            party.ledger = existing
            party.save(update_fields=["ledger"])
            return existing
        # The name belongs to some other ledger. Tell them apart by the GSTIN's tail, or by the side.
        tail = party.gstin[-4:] if party.gstin else ""
        name = f"{name} ({tail or ('Creditor' if side == LedgerGroup.CREDITOR else 'Debtor')})"
        if ledgers.filter(name=name).exists():
            raise BillingError(f"This client already has a ledger named {name!r}. Rename one of them first.")

    ledger = LedgerAccount.objects.create(firm_id=party.firm_id, client=party.client, name=name, group=side)
    party.ledger = ledger
    party.save(update_fields=["ledger"])
    return ledger


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

_KIND_RULES = {
    BillKind.PURCHASE: (VoucherType.PURCHASE, CR, (PartyRole.VENDOR, PartyRole.BOTH), LedgerGroup.CREDITOR),
    BillKind.DEBIT_NOTE: (VoucherType.DEBIT_NOTE, DR, (PartyRole.VENDOR, PartyRole.BOTH), LedgerGroup.CREDITOR),
    BillKind.SALES: (VoucherType.SALES, DR, (PartyRole.CUSTOMER, PartyRole.BOTH), LedgerGroup.DEBTOR),
    BillKind.CREDIT_NOTE: (VoucherType.CREDIT_NOTE, CR, (PartyRole.CUSTOMER, PartyRole.BOTH), LedgerGroup.DEBTOR),
}


@dataclass(frozen=True)
class BillInput:
    """Everything about a voucher that is not its lines."""

    reference: str
    bill_date: datetime.date
    due_date: datetime.date | None = None
    narration: str = ""
    document: object | None = None
    #: The client's own GSTIN this belongs to, so the bill lands in the right return.
    own_gstin: str = ""
    cgst: int = 0
    sgst: int = 0
    igst: int = 0
    cess: int = 0
    round_off: int = 0
    tds: int = 0
    tds_section: str = ""
    rcm: bool = False
    extra: dict = field(default_factory=dict)


def _post(client, party, kind, plan: VoucherPlan, data: BillInput, *, membership) -> Bill:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)

    voucher_type, direction, roles, side = _KIND_RULES[kind]
    reference = (data.reference or "").strip()
    if not reference or len(reference) > 64:
        raise BillingError("An invoice number is required, up to 64 characters.")
    if party.client_id != client.pk or party.firm_id != client.firm_id:
        raise BillingError("That party belongs to a different client.")
    if party.role not in roles:
        raise BillingError(
            f"{party.canonical_name} is recorded as {party.get_role_display().lower()}, "
            f"which cannot have a {kind.lower().replace('_', ' ')}. Change the party's role first."
        )

    through = editing.locked_through(client.pk)
    if through is not None and data.bill_date <= through:
        raise BillingError(
            f"The books are signed off through {through:%d-%m-%Y}, so nothing can be booked dated "
            f"{data.bill_date:%d-%m-%Y}. Date it after the sign-off, or ask a senior to reopen the books."
        )

    year = financial_year(data.bill_date)
    identity = supplier_identity(party.gstin, party.pk) if kind in (BillKind.PURCHASE, BillKind.DEBIT_NOTE) else (
        supplier_identity(data.own_gstin, client.pk)
    )
    key = invoice_key(client.firm_id, identity, reference)
    if Bill.objects.filter(firm_id=client.firm_id, client=client, kind=kind, financial_year=year, invoice_key=key).exists():
        raise BillingError(
            f"{party.canonical_name}'s {kind.lower().replace('_', ' ')} {reference!r} is already booked for "
            f"FY {year}-{(year + 1) % 100:02d}. A duplicate would count it twice."
        )
    if data.document is not None and data.document.client_id != client.pk:
        raise BillingError("That document belongs to a different client.")

    party_ledger = party_ledger_for(party, side=side)
    resolved = {PARTY: party_ledger}
    for line in plan.lines:
        ledger = line.ledger
        if ledger is PARTY or ledger == PARTY:
            continue
        if isinstance(ledger, str):
            resolved[ledger] = standard_ledger(client, ledger)
            continue
        if ledger.client_id != client.pk:
            raise BillingError(f"The ledger {ledger.name!r} belongs to a different client.")
        if ledger.status != LedgerStatus.ACTIVE:
            raise BillingError(f"The ledger {ledger.name!r} is not in use yet; a CA must accept it first.")
        if ledger.group in _NOT_A_HEAD or ledger.pk == party_ledger.pk:
            raise BillingError(
                f"{ledger.name!r} is a bank, cash or party account. An invoice's heads are what was bought or sold."
            )

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            firm_id=client.firm_id,
            client=client,
            entry_no=approval.allocate_voucher_number(client, year, voucher_type),
            financial_year=year,
            entry_date=data.bill_date,
            voucher_type=voucher_type,
            entry_kind=EntryKind.VOUCHER,
            narration=data.narration.strip()
            or f"Being {kind.lower().replace('_', ' ')} {reference} of {party.canonical_name}",
            approved_by=membership.user,
            approved_at=timezone.now(),
        )
        lines = []
        for planned in plan.lines:
            is_party = planned.ledger is PARTY or planned.ledger == PARTY
            lines.append(
                JournalLine.build(
                    entry=entry,
                    ledger_account=party_ledger if is_party else resolved.get(planned.ledger, planned.ledger),
                    party=party if is_party else None,
                    direction=planned.direction,
                    amount_paise=planned.amount_paise,
                    rcm=planned.rcm,
                    tds_section=planned.tds_section,
                )
            )
        JournalLine.objects.bulk_create(lines)

        try:
            with transaction.atomic():
                bill = Bill.objects.create(
                    firm_id=client.firm_id,
                    client=client,
                    party=party,
                    kind=kind,
                    direction=direction,
                    reference=reference,
                    bill_date=data.bill_date,
                    due_date=data.due_date,
                    booked_on=data.bill_date,
                    financial_year=year,
                    taxable_paise=plan.taxable_paise,
                    cgst_paise=data.cgst,
                    sgst_paise=data.sgst,
                    igst_paise=data.igst,
                    cess_paise=data.cess,
                    round_off_paise=data.round_off,
                    tds_paise=data.tds,
                    rcm=data.rcm,
                    total_paise=plan.party_paise,
                    entry=entry,
                    document=data.document,
                    invoice_key=key,
                    own_gstin_hash=(
                        blind_index(normalise_gstin(data.own_gstin), client.firm_id, CRYPTO_PURPOSE)
                        if normalise_gstin(data.own_gstin)
                        else ""
                    ),
                )
        except IntegrityError as exc:  # a concurrent booking of the same invoice
            raise BillingError("That invoice was booked a moment ago by someone else.") from exc
    return bill


def _heads(heads):
    return [(ledger, int(amount)) for ledger, amount in heads]


def post_purchase(client, party, heads, data: BillInput, *, membership) -> Bill:
    """Book a supplier's invoice. See ``plan_purchase`` for the lines it writes."""
    plan = plan_purchase(
        _heads(heads), cgst=data.cgst, sgst=data.sgst, igst=data.igst, cess=data.cess,
        round_off=data.round_off, tds=data.tds, rcm=data.rcm, tds_section=data.tds_section,
    )
    return _post(client, party, BillKind.PURCHASE, plan, data, membership=membership)


def post_sales(client, party, heads, data: BillInput, *, membership) -> Bill:
    """Book our invoice to a customer. See ``plan_sales``."""
    if data.tds or data.rcm:
        raise BillingError("A customer's TDS is booked when they pay, and reverse charge does not apply to our sales.")
    plan = plan_sales(
        _heads(heads), cgst=data.cgst, sgst=data.sgst, igst=data.igst, cess=data.cess,
        round_off=data.round_off,
    )
    return _post(client, party, BillKind.SALES, plan, data, membership=membership)


def post_debit_note(client, party, heads, data: BillInput, *, membership) -> Bill:
    """Book a purchase return to a supplier."""
    plan = plan_debit_note(
        _heads(heads), cgst=data.cgst, sgst=data.sgst, igst=data.igst, cess=data.cess,
        round_off=data.round_off,
    )
    return _post(client, party, BillKind.DEBIT_NOTE, plan, data, membership=membership)


def post_credit_note(client, party, heads, data: BillInput, *, membership) -> Bill:
    """Book a sales return from a customer."""
    plan = plan_credit_note(
        _heads(heads), cgst=data.cgst, sgst=data.sgst, igst=data.igst, cess=data.cess,
        round_off=data.round_off,
    )
    return _post(client, party, BillKind.CREDIT_NOTE, plan, data, membership=membership)


def _reopen_reading(bill: Bill) -> None:
    """The uploaded invoice this bill was booked from or attached to waits again for a person once the bill is gone."""
    from ledger.models import InvoiceReading, ReadingStatus

    InvoiceReading.objects.filter(bill=bill).update(
        bill=None, status=ReadingStatus.OPEN, auto_booked=False, decided_by=None, decided_at=None
    )


@transaction.atomic
def remove_bill(bill: Bill, *, membership, note: str = "", release_payments: bool = False) -> None:
    """Take an unsigned bill out of the books, with its voucher. The change log keeps what it was.

    A bill with payments settled against it is refused unless ``release_payments`` is said: its allocations are then undone
    (each payment stays on the party's account, unallocated, to be settled against something else), but only when every
    payment is itself inside open books, so nothing signed off is touched.
    """
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, bill.client)
    bill = Bill.objects.select_for_update().get(pk=bill.pk)

    allocations = list(bill.allocations.select_related("line__entry"))
    if allocations:
        if not release_payments:
            raise BillingError(
                f"{bill.reference!r} has payments or adjustments allocated to it. Release them as part of the delete, "
                f"or record a debit or credit note instead."
            )
        for allocation in allocations:
            if allocation.line_id is not None:
                editing.require_editable(allocation.line.entry)
        # What is un-linked is written into the change log with the removal, so the trail shows which payments were released.
        released = "; ".join(
            f"{a.line.entry.voucher_type} No. {a.line.entry.entry_no} of {a.line.entry.entry_date:%d-%m-%Y}, Rs {a.amount_paise / 100:,.2f}"
            for a in allocations
            if a.line_id is not None
        )
        if released:
            note = (f"{note} " if note else "") + f"Payments released from this bill: {released}."
            note = note[:500]
        for allocation in allocations:
            allocation.delete()
    _reopen_reading(bill)
    entry = bill.entry
    if entry is None:
        through = editing.locked_through(bill.client_id)
        if through is not None and bill.booked_on <= through:
            raise BillingError("This opening balance is inside books that have been signed off.")
        bill.delete()
        return

    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    editing.require_editable(entry)
    before = editing.snapshot(entry)
    editing.record_change(entry, ChangeAction.REMOVED, actor=membership.user, before=before, note=note)
    bill.delete()
    entry.lines.all().delete()
    entry.delete()


# ---------------------------------------------------------------------------
# Settlement: a line on a party's ledger settles bills, or waits
# ---------------------------------------------------------------------------


def open_amount(bill: Bill) -> int:
    """What is still unsettled on a bill. Computed from allocations, never stored."""
    settled = bill.allocations.aggregate(total=Sum("amount_paise"))["total"] or 0
    return bill.total_paise - settled


def line_unallocated(line: JournalLine) -> int:
    """What part of a settling line has not been allocated to anything yet."""
    used = line.allocations.aggregate(total=Sum("amount_paise"))["total"] or 0
    return line.amount_paise - used


@transaction.atomic
def allocate(line: JournalLine, *, amount_paise: int, bill: Bill | None = None, kind: str | None = None) -> BillAllocation:
    """Allocate part of a settling line to a bill, or leave it on account or as an advance.

    The database refuses anything this lets through (see ``ledger/0012``); these checks are here to say why in words.
    """
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise BillingError("An allocation must be an amount above zero, in whole paise.")
    if line.party_id is None:
        raise BillingError("Only a line that names a party can settle a bill.")

    kind = kind or (AllocationKind.AGAINST_BILL if bill is not None else AllocationKind.ON_ACCOUNT)
    if (kind == AllocationKind.AGAINST_BILL) != (bill is not None):
        raise BillingError("An allocation names a bill if and only if it is against a bill.")

    line = JournalLine.objects.select_for_update().get(pk=line.pk)
    if amount_paise > line_unallocated(line):
        raise BillingError(
            f"Only {line_unallocated(line)} paise of this line is left to allocate, not {amount_paise}."
        )
    if bill is not None:
        bill = Bill.objects.select_for_update().get(pk=bill.pk)
        if bill.party_id != line.party_id:
            raise BillingError("A payment can only settle a bill of the same party.")
        if bill.direction == line.direction:
            raise BillingError("A bill is settled by a line on the opposite side of the party's ledger.")
        if amount_paise > open_amount(bill):
            raise BillingError(f"Only {open_amount(bill)} paise of that bill is still open, not {amount_paise}.")

    return BillAllocation.objects.create(
        firm_id=line.firm_id, client_id=line.entry.client_id, line=line, bill=bill, kind=kind, amount_paise=amount_paise
    )


@transaction.atomic
def apply_unapplied(allocation: BillAllocation, bill: Bill, *, amount_paise: int) -> BillAllocation:
    """Turn money held on account or as an advance into a settlement of a bill that has since arrived."""
    if allocation.kind == AllocationKind.AGAINST_BILL:
        raise BillingError("That allocation already settles a bill.")
    allocation = BillAllocation.objects.select_for_update().get(pk=allocation.pk)
    if amount_paise <= 0 or amount_paise > allocation.amount_paise:
        raise BillingError("The amount to apply must be above zero and no more than is held.")

    line, firm_id, client_id = allocation.line, allocation.firm_id, allocation.client_id
    remaining = allocation.amount_paise - amount_paise
    allocation.delete()
    if remaining:
        BillAllocation.objects.create(
            firm_id=firm_id, client_id=client_id, line=line, bill=None, kind=allocation.kind, amount_paise=remaining
        )
    return allocate(line, bill=bill, amount_paise=amount_paise)


# ---------------------------------------------------------------------------
# Reading a party's position
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartyPosition:
    """Where a party stands, from the ledger and from the bills, side by side.

    Signed like the ledger: debits positive, so a supplier the client owes is negative. ``difference`` is the ledger
    balance less everything the bills and unapplied settlements explain, and is zero when the party reconciles.
    """

    ledger_balance_paise: int
    open_bills_paise: int
    unapplied_paise: int

    @property
    def difference_paise(self) -> int:
        return self.ledger_balance_paise - (self.open_bills_paise + self.unapplied_paise)

    @property
    def reconciles(self) -> bool:
        return self.difference_paise == 0


def party_position(party: Party) -> PartyPosition:
    """Compare the party's ledger with its bills. The first control-account check.

    ``open_bills`` is every bill's unsettled amount, signed by the side it sits on. ``unapplied`` is every settling line's
    unallocated remainder plus money held on account or as an advance. An opening balance shows in the ledger through
    ``LedgerOpening`` and in the bills as ``OPENING`` bills, and the check fails if they disagree.
    """
    if not party.ledger_id:
        return PartyPosition(0, 0, 0)
    ledger = party.ledger
    opening = (
        LedgerOpening.objects.filter(firm_id=party.firm_id, ledger=ledger).order_by("financial_year").first()
    )
    posted = JournalLine.objects.filter(firm_id=party.firm_id, ledger_account=ledger).aggregate(
        total=Sum("signed_paise")
    )["total"] or 0

    bills = Bill.objects.filter(firm_id=party.firm_id, party=party)
    open_bills = sum((1 if bill.direction == DR else -1) * open_amount(bill) for bill in bills)

    bill_entries = [bill.entry_id for bill in bills if bill.entry_id]
    unapplied = 0
    lines = JournalLine.objects.filter(firm_id=party.firm_id, ledger_account=ledger).exclude(entry_id__in=bill_entries)
    for line in lines:
        against = line.allocations.filter(kind=AllocationKind.AGAINST_BILL).aggregate(total=Sum("amount_paise"))["total"] or 0
        unapplied += (1 if line.direction == DR else -1) * (line.amount_paise - against)

    return PartyPosition(
        ledger_balance_paise=(opening.signed_paise if opening else 0) + posted,
        open_bills_paise=open_bills,
        unapplied_paise=unapplied,
    )
