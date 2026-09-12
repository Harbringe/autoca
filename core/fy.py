"""The Indian financial year: 1 April to 31 March.

Small enough to inline and important enough not to. Every voucher number, every
report range and every GST return period is scoped to a financial year, and a
codebase that computes it in six places will eventually compute it differently
in one of them -- most likely in the two weeks either side of 31 March, where
the mistake is hardest to spot and most expensive.

The label form is ``2025-26``: the convention every Indian accountant, portal
and return already uses. Not ``2025`` and not ``2025-2026``.
"""

from __future__ import annotations

import datetime

#: The month a financial year starts. April.
FY_START_MONTH = 4


def financial_year(when: datetime.date) -> int:
    """The starting calendar year of the financial year containing ``when``.

    31 March 2026 belongs to FY 2025-26 and returns 2025; 1 April 2026 belongs
    to FY 2026-27 and returns 2026.
    """
    return when.year if when.month >= FY_START_MONTH else when.year - 1


def fy_label(when: datetime.date) -> str:
    """``2025-26`` for any date in that financial year."""
    start = financial_year(when)
    return f"{start}-{(start + 1) % 100:02d}"


def fy_bounds(start_year: int) -> tuple[datetime.date, datetime.date]:
    """First and last day of the financial year beginning in ``start_year``."""
    return (
        datetime.date(start_year, FY_START_MONTH, 1),
        datetime.date(start_year + 1, FY_START_MONTH, 1) - datetime.timedelta(days=1),
    )


def fy_contains(start_year: int, when: datetime.date) -> bool:
    first, last = fy_bounds(start_year)
    return first <= when <= last
