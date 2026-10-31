"""Cutting a large vouchers export into one piece per calendar month, so each can be reviewed, posted and undone on its own."""

from __future__ import annotations

from collections.abc import Sequence

from ledger.tally_vouchers import ParsedVoucher


def split_by_month(vouchers: Sequence[ParsedVoucher]) -> list[tuple[str, list[ParsedVoucher]]]:
    """``("2025-04", [...])`` per month, oldest first; every voucher in exactly one month, in the file's order within it."""
    months: dict[str, list[ParsedVoucher]] = {}
    for voucher in vouchers:
        months.setdefault(f"{voucher.date.year}-{voucher.date.month:02d}", []).append(voucher)
    return sorted(months.items())
