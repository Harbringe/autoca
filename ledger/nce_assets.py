"""Note 11: the block of Property, Plant and Equipment and Intangible assets, class by class, from the asset register.

The format wants, for each class of asset, the gross block (at 1 April, additions, deductions, at 31 March), the depreciation
on it (at 1 April, for the year, on deductions, at 31 March) and the net block at both year ends. The ledgers carry only a
balance, so this comes from the register (``ledger.models.FixedAsset``), whose depreciation is computed by
``ledger.depreciation`` from each asset's terms.

The register and the ledgers are the same money seen twice, so the note says when they disagree (``tie_out``) rather than
quietly presenting one of them.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from ledger import depreciation


@dataclass(frozen=True)
class AssetFacts:
    """What the block needs to know of one asset."""

    kind: str
    cost_paise: int
    put_to_use: datetime.date
    disposed_on: datetime.date | None
    #: The asset's year-by-year position, from the year it was put to use (``ledger.depreciation.schedule``).
    rows: tuple[depreciation.YearRow, ...]


@dataclass(frozen=True)
class Block:
    gross_open: int = 0
    additions: int = 0
    deductions: int = 0
    dep_open: int = 0
    dep_year: int = 0
    dep_deductions: int = 0

    @property
    def gross_close(self) -> int:
        return self.gross_open + self.additions - self.deductions

    @property
    def dep_close(self) -> int:
        return self.dep_open + self.dep_year - self.dep_deductions

    @property
    def net_close(self) -> int:
        return self.gross_close - self.dep_close

    def __add__(self, other: Block) -> Block:
        return Block(*(a + b for a, b in zip(self._parts(), other._parts(), strict=True)))

    def _parts(self) -> tuple[int, ...]:
        return (self.gross_open, self.additions, self.deductions, self.dep_open, self.dep_year, self.dep_deductions)


def _accumulated(rows: Iterable[depreciation.YearRow], year: int) -> int:
    return next((r.accumulated_paise for r in rows if r.financial_year == year), 0)


def block_for(assets: Iterable[AssetFacts], year: int) -> dict[str, Block]:
    """The block for the financial year starting in ``year``, by class."""
    start, end = depreciation.fy_bounds(year)
    out: dict[str, Block] = {}
    for a in assets:
        in_use_at_start = a.put_to_use < start and not (a.disposed_on and a.disposed_on < start)
        added = start <= a.put_to_use <= end
        sold = bool(a.disposed_on and start <= a.disposed_on <= end)
        row = next((r for r in a.rows if r.financial_year == year), None)
        out[a.kind] = out.get(a.kind, Block()) + Block(
            gross_open=a.cost_paise if in_use_at_start else 0,
            additions=a.cost_paise if added else 0,
            deductions=a.cost_paise if sold else 0,
            dep_open=_accumulated(a.rows, year - 1) if in_use_at_start else 0,
            dep_year=row.depreciation_paise if row else 0,
            dep_deductions=(row.accumulated_paise if row else 0) if sold else 0,
        )
    return out


def facts_of(client, year: int, kind_of) -> list[AssetFacts]:
    """The client's register as facts through ``year``. ``kind_of(asset)`` names the class an asset belongs to."""
    from ledger.assets import terms_of
    from ledger.models import FixedAsset

    out = []
    for asset in FixedAsset.objects.filter(firm_id=client.firm_id, client=client).select_related("ledger"):
        rows = depreciation.schedule(terms_of(asset), through_year=year)
        out.append(AssetFacts(kind_of(asset), asset.cost_paise, asset.put_to_use, asset.disposed_on, tuple(rows)))
    return out
