"""How a voucher's number reads: the stored integer, with the prefix and padding its series has been given.

The number in the book never changes with the format; only what is shown does. A series (a standard voucher type, or a firm's own
type such as "GST SALE") has at most one format, and a series without one shows the plain number.
"""

from __future__ import annotations

from ledger.models import NumberingFormat


def load_formats(client) -> dict[tuple[str, str], NumberingFormat]:
    """Every format the client has set, keyed by ``(voucher_type, type_name)``. One query, for a list that shows many numbers."""
    rows = NumberingFormat.objects.filter(firm_id=client.firm_id, client=client)
    return {(row.voucher_type, row.type_name): row for row in rows}


def format_voucher_number(
    client,
    voucher_type: str,
    type_name: str,
    number: int,
    financial_year: int,
    *,
    formats: dict[tuple[str, str], NumberingFormat] | None = None,
) -> str:
    """``S/25-26/0007`` for number 7 of FY 2025-26 under prefix ``S/{fy}/`` and padding 4; ``7`` when the series has no format."""
    formats = load_formats(client) if formats is None else formats
    fmt = formats.get((voucher_type, type_name))
    if fmt is None:
        return str(number)
    prefix = fmt.prefix.replace("{fy}", f"{financial_year % 100:02d}-{(financial_year + 1) % 100:02d}")
    return f"{prefix}{number:0{fmt.padding}d}" if fmt.padding else f"{prefix}{number}"


class VoucherTypeInUseError(RuntimeError):
    """A firm's own voucher type has vouchers under it, so it cannot be renamed, moved to another parent or removed."""


def is_in_use(custom_type) -> bool:
    """Do any vouchers of this client carry the firm's own voucher type?"""
    from ledger.models import JournalEntry

    return JournalEntry.objects.filter(firm_id=custom_type.firm_id, client_id=custom_type.client_id, type_name=custom_type.name).exists()
