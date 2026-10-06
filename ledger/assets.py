"""The asset register: assets bought through the books, and what each is worth year by year.

An asset's cost is the money a purchase already put on a fixed-asset ledger, so the register is tied to the books rather
than keyed in beside them. A purchase that debits a fixed-asset ledger and is not in the register is an open item
(``fixed_asset_unregistered``); registering it takes its cost from the purchase and cannot exceed what the purchase put there.
Depreciation is computed from the terms (``ledger.depreciation``) each time it is asked for, never stored.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum

from classify.models import LedgerAccount, LedgerGroup, LedgerStatus
from core.access import require_posting_rights
from core.rbac import require_permission
from ledger import depreciation
from ledger.models import Bill, BillKind, Direction, FixedAsset, JournalLine


class AssetError(ValueError):
    """The register cannot take this. The message says what to change."""


def asset_lines(bill: Bill) -> dict:
    """What a purchase put on fixed-asset ledgers: ledger id -> paise debited."""
    if bill.entry_id is None:
        return {}
    rows = (
        JournalLine.objects.filter(
            entry_id=bill.entry_id, ledger_account__group=LedgerGroup.FIXED_ASSET, direction=Direction.DEBIT
        )
        .values("ledger_account_id")
        .annotate(total=Sum("amount_paise"))
    )
    return {row["ledger_account_id"]: row["total"] for row in rows}


def registered(bill: Bill, ledger_id=None) -> int:
    queryset = FixedAsset.objects.filter(firm_id=bill.firm_id, bill=bill)
    if ledger_id is not None:
        queryset = queryset.filter(ledger_id=ledger_id)
    return queryset.aggregate(total=Sum("cost_paise"))["total"] or 0


def unregistered(bill: Bill) -> int:
    """How much of what the purchase put on fixed-asset ledgers is not in the register yet."""
    return max(sum(asset_lines(bill).values()) - registered(bill), 0)


def terms_of(asset: FixedAsset, *, disposed_on=None) -> depreciation.AssetTerms:
    return depreciation.AssetTerms(
        cost_paise=asset.cost_paise,
        put_to_use=asset.put_to_use,
        method=asset.method,
        life_years=asset.life_years,
        rate_bp=asset.rate_bp,
        residual_paise=asset.residual_paise,
        disposed_on=disposed_on or asset.disposed_on,
    )


@transaction.atomic
def register_asset(
    client,
    *,
    name: str,
    ledger: LedgerAccount,
    cost_paise: int,
    put_to_use: datetime.date,
    method: str,
    membership,
    bill: Bill | None = None,
    life_years: int = 0,
    rate_bp: int = 0,
    residual_paise: int = 0,
) -> FixedAsset:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    name = " ".join((name or "").split())
    if not name:
        raise AssetError("Give the asset a name.")
    if ledger.client_id != client.pk or ledger.firm_id != client.firm_id:
        raise AssetError("That ledger belongs to a different client.")
    if ledger.group != LedgerGroup.FIXED_ASSET:
        raise AssetError(f"{ledger.name!r} is not a fixed-asset ledger. Choose a ledger under Fixed Assets.")
    if ledger.status != LedgerStatus.ACTIVE or not ledger.is_active:
        raise AssetError(f"The ledger {ledger.name!r} is not in use.")

    if bill is not None:
        if bill.client_id != client.pk or bill.firm_id != client.firm_id:
            raise AssetError("That purchase belongs to a different client.")
        if bill.kind != BillKind.PURCHASE:
            raise AssetError("An asset is registered from a purchase invoice.")
        lines = asset_lines(bill)
        if ledger.pk not in lines:
            raise AssetError(f"That purchase put nothing on {ledger.name!r}.")
        room = lines[ledger.pk] - registered(bill, ledger.pk)
        if cost_paise > room:
            raise AssetError(
                f"That purchase put {lines[ledger.pk]} paise on {ledger.name!r} and {lines[ledger.pk] - room} is already "
                f"registered, so at most {room} paise can be added."
            )

    terms = depreciation.AssetTerms(
        cost_paise=cost_paise, put_to_use=put_to_use, method=method, life_years=life_years, rate_bp=rate_bp,
        residual_paise=residual_paise,
    )
    problem = depreciation.validate(terms)
    if problem:
        raise AssetError(problem)
    return FixedAsset.objects.create(
        firm_id=client.firm_id, client=client, name=name[:200], ledger=ledger, bill=bill, cost_paise=cost_paise,
        residual_paise=residual_paise, put_to_use=put_to_use, method=method, life_years=life_years, rate_bp=rate_bp,
    )


@transaction.atomic
def dispose(asset: FixedAsset, *, on: datetime.date, proceeds_paise: int, membership) -> FixedAsset:
    """Record the sale of an asset. Depreciation stops at that day; the entry for the sale is booked as usual."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, asset.client)
    if asset.disposed_on:
        raise AssetError("This asset has already been sold.")
    if proceeds_paise < 0:
        raise AssetError("The sale price cannot be negative.")
    problem = depreciation.validate(terms_of(asset, disposed_on=on))
    if problem:
        raise AssetError(problem)
    asset.disposed_on = on
    asset.disposal_paise = proceeds_paise
    asset.save(update_fields=["disposed_on", "disposal_paise"])
    return asset


@transaction.atomic
def remove(asset: FixedAsset, *, membership) -> None:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, asset.client)
    asset.delete()


@dataclass(frozen=True)
class AssetYear:
    asset: FixedAsset
    row: depreciation.YearRow


def schedule(client, year: int) -> list[AssetYear]:
    """Each asset's position for the financial year starting in ``year``. Assets not yet in use, or sold earlier, are left out."""
    out = []
    for asset in FixedAsset.objects.filter(firm_id=client.firm_id, client=client).select_related("ledger"):
        rows = depreciation.schedule(terms_of(asset), through_year=year)
        row = next((r for r in rows if r.financial_year == year), None)
        if row is not None:
            out.append(AssetYear(asset, row))
    return out
