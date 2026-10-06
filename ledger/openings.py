"""Opening balances of parties, broken into the bills that make them up.

A Tally chart import brings each supplier's and customer's balance as one number (``LedgerOpening``) on a ledger that has no
party behind it. Left like that it is an island: the party's ledger says "owes 50,000" and its bills say nothing, so no
payment can be settled against what is really outstanding and the control check never agrees.

Two steps join it to the rest of the books:

* ``adopt_imported_party_ledgers`` gives every imported Sundry Debtor and Creditor ledger a ``Party`` (linked by a real foreign
  key, as a first voucher would), so its name, aliases and bills have somewhere to live.
* ``post_opening_bills`` breaks the party's opening balance into ``OPENING`` bills (invoice number, date, amount). They make no
  journal entry, because the opening balance is already in the ledger; they only say what it is made of, so payments settle
  against them like any bill and ``party_position`` reconciles. They may not add up to more than the opening balance, and
  what is not yet broken down stays a visible open item.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from classify.models import LedgerAccount, LedgerGroup, Party, PartyRole
from core.access import require_posting_rights
from core.identity import invoice_key, supplier_identity
from core.rbac import require_permission
from ledger import editing
from ledger.billing import CR, DR, BillingError
from ledger.models import Bill, BillKind, LedgerOpening


def adopt_imported_party_ledgers(client) -> int:
    """Give each Sundry Debtors and Creditors ledger that has no party one, linked to it. Returns how many were made or linked.

    A party of the same name that has no ledger yet is linked to the ledger rather than duplicated. Idempotent.
    """
    adopted = 0
    ledgers = LedgerAccount.objects.filter(
        firm_id=client.firm_id,
        client=client,
        group__in=(LedgerGroup.DEBTOR, LedgerGroup.CREDITOR),
        party_record__isnull=True,
    )
    for ledger in ledgers:
        name = " ".join(ledger.name.split())
        role = PartyRole.CUSTOMER if ledger.group == LedgerGroup.DEBTOR else PartyRole.VENDOR
        party = Party.objects.filter(firm_id=client.firm_id, client=client, canonical_name=name).first()
        if party is None:
            Party.objects.create(firm_id=client.firm_id, client=client, canonical_name=name, role=role, ledger=ledger)
            adopted += 1
        elif party.ledger_id is None:
            party.ledger = ledger
            party.save(update_fields=["ledger"])
            adopted += 1
    return adopted


@dataclass(frozen=True)
class OpeningStanding:
    """A party's imported opening balance and how much of it is already broken into bills."""

    financial_year: int | None
    #: Signed like the ledger: debits positive, so a supplier the client owes is negative.
    opening_paise: int
    billed_paise: int

    @property
    def direction(self) -> str | None:
        if self.opening_paise == 0:
            return None
        return DR if self.opening_paise > 0 else CR

    @property
    def remaining_paise(self) -> int:
        return abs(self.opening_paise) - self.billed_paise


def opening_standing(party: Party) -> OpeningStanding:
    if not party.ledger_id:
        return OpeningStanding(None, 0, 0)
    opening = (
        LedgerOpening.objects.filter(firm_id=party.firm_id, ledger_id=party.ledger_id).order_by("financial_year").first()
    )
    if opening is None:
        return OpeningStanding(None, 0, 0)
    billed = sum(
        bill.total_paise
        for bill in Bill.objects.filter(
            firm_id=party.firm_id, party=party, kind=BillKind.OPENING, financial_year=opening.financial_year
        )
    )
    return OpeningStanding(opening.financial_year, opening.signed_paise, billed)


@dataclass(frozen=True)
class OpeningBillInput:
    reference: str
    bill_date: datetime.date
    amount_paise: int
    due_date: datetime.date | None = None


def post_opening_bills(client, party: Party, bills: list[OpeningBillInput], *, membership) -> list[Bill]:
    """Break part or all of a party's opening balance into bills. All or nothing."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    if party.client_id != client.pk or party.firm_id != client.firm_id:
        raise BillingError("That party belongs to a different client.")
    if not bills:
        raise BillingError("Give at least one bill.")

    with transaction.atomic():
        # One breakdown at a time per party, so two people cannot together exceed the balance.
        Party.objects.select_for_update().get(pk=party.pk, firm_id=party.firm_id)
        standing = opening_standing(party)
        if standing.direction is None or standing.financial_year is None:
            raise BillingError(f"{party.canonical_name} has no opening balance to break into bills.")
        year_start = datetime.date(standing.financial_year, 4, 1)
        through = editing.locked_through(client.pk)
        if through is not None and year_start <= through:
            raise BillingError(
                f"The books are signed off through {through:%d-%m-%Y}, so the opening balance dated "
                f"{year_start:%d-%m-%Y} can no longer be broken into bills. Ask a senior to reopen the books."
            )

        total = 0
        seen: set[str] = set()
        created: list[Bill] = []
        for item in bills:
            reference = (item.reference or "").strip()
            if not reference or len(reference) > 64:
                raise BillingError("Each bill needs an invoice number, up to 64 characters.")
            if item.amount_paise <= 0:
                raise BillingError(f"The amount of {reference!r} must be more than zero.")
            if item.bill_date >= year_start:
                raise BillingError(
                    f"{reference!r} is dated {item.bill_date:%d-%m-%Y}, which is not before the balance "
                    f"({year_start:%d-%m-%Y}). A bill from this year is booked as a voucher, not as an opening."
                )
            key = invoice_key(client.firm_id, supplier_identity(party.gstin, party.pk), reference)
            if key in seen:
                raise BillingError(f"{reference!r} is listed twice.")
            seen.add(key)
            total += item.amount_paise
            try:
                with transaction.atomic():
                    created.append(
                        Bill.objects.create(
                            firm_id=client.firm_id,
                            client=client,
                            party=party,
                            kind=BillKind.OPENING,
                            direction=standing.direction,
                            reference=reference,
                            bill_date=item.bill_date,
                            due_date=item.due_date,
                            booked_on=year_start,
                            financial_year=standing.financial_year,
                            taxable_paise=item.amount_paise,
                            total_paise=item.amount_paise,
                            entry=None,
                            invoice_key=key,
                        )
                    )
            except IntegrityError as exc:
                raise BillingError(f"{party.canonical_name}'s opening bill {reference!r} is already listed.") from exc

        if total > standing.remaining_paise:
            raise BillingError(
                f"These bills add up to more than is left of {party.canonical_name}'s opening balance "
                f"({standing.remaining_paise} paise left). The balance cannot be exceeded."
            )
    return created
