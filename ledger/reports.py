"""Trial Balance, Profit & Loss, Balance Sheet.

Straightforward aggregations over ``JournalLine`` -- at pilot volume there is
nothing clever to do here and nothing clever should be done. What matters is
not the arithmetic but two things around it.

**Every report states what it was built from.** A report generated while forty
transactions still sit in the review queue is not wrong, but it is incomplete,
and a firm that hands it to a client without knowing that has been let down by
the software. So every report carries its financial year, the entries behind it,
and the count still awaiting approval -- and says so where a reader will see it,
not in a log.

**Only approved entries count.** A suggestion is not a book entry. This is the
same boundary the exporter draws, for the same reason.

A superseded entry is *included*, deliberately. Its correction carries a
reversal of it, so the two net to the corrected position; dropping the original
would double-count the reversal and put the trial balance out by exactly the
amount that was corrected. The chain nets correctly at every point, which is why
corrections are recorded that way.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db.models import Q, Sum
from django.utils import timezone

from classify.models import LedgerGroup
from core.fy import fy_bounds, fy_label
from core.money import format_inr
from ledger.models import JournalLine

#: Groups whose balances belong to the Profit & Loss statement. Everything else
#: is a balance-sheet item.
PROFIT_AND_LOSS_GROUPS = frozenset(
    {
        LedgerGroup.DIRECT_INCOME,
        LedgerGroup.INDIRECT_INCOME,
        LedgerGroup.DIRECT_EXPENSE,
        LedgerGroup.INDIRECT_EXPENSE,
    }
)

#: Balance-sheet groups that normally carry a debit balance.
ASSET_GROUPS = frozenset(
    {LedgerGroup.BANK, LedgerGroup.CASH, LedgerGroup.DEBTOR, LedgerGroup.INVESTMENT}
)

INCOME_GROUPS = frozenset({LedgerGroup.DIRECT_INCOME, LedgerGroup.INDIRECT_INCOME})


@dataclass(frozen=True)
class ReportFooter:
    """What a reader needs in order to trust, or distrust, the figures above."""

    client_name: str
    financial_year: int
    period_start: datetime.date
    period_end: datetime.date
    entry_count: int
    #: Transactions classified but not yet approved. Anything above zero means
    #: the report is a snapshot of incomplete books.
    pending_review: int
    generated_at: datetime.datetime

    @property
    def fy_label(self) -> str:
        return fy_label(self.period_start)

    @property
    def is_complete(self) -> bool:
        return self.pending_review == 0

    def caption(self) -> str:
        line = (
            f"{self.client_name} · FY {self.fy_label} · {self.entry_count} entries · "
            f"generated {timezone.localtime(self.generated_at):%d-%m-%Y %H:%M}"
        )
        if self.is_complete:
            return line
        return (
            f"{line}\nINCOMPLETE: {self.pending_review} transaction(s) are classified "
            f"but not approved and are not included in these figures."
        )


@dataclass(frozen=True)
class LedgerBalance:
    """One ledger account's opening, movement and closing position for the period.

    ``debit_paise`` and ``credit_paise`` are the year's movement only -- what
    Tally prints as a ledger's totals. ``opening_paise`` is everything before the
    year: a balance-sheet ledger's history and a confirmed bank opening balance.
    Income and expense ledgers start every year at zero.
    """

    name: str
    group: str
    debit_paise: int
    credit_paise: int
    #: Debits positive, like ``net_paise``.
    opening_paise: int = 0

    @property
    def net_paise(self) -> int:
        """The closing position. Debits positive: a bank in funds is positive, income negative."""
        return self.opening_paise + self.debit_paise - self.credit_paise

    @property
    def closing_debit_paise(self) -> int:
        return max(self.net_paise, 0)

    @property
    def closing_credit_paise(self) -> int:
        return max(-self.net_paise, 0)

    @property
    def is_profit_and_loss(self) -> bool:
        return self.group in PROFIT_AND_LOSS_GROUPS


@dataclass(frozen=True)
class TrialBalance:
    rows: tuple[LedgerBalance, ...]
    footer: ReportFooter

    @property
    def total_debit_paise(self) -> int:
        return sum(row.closing_debit_paise for row in self.rows)

    @property
    def total_credit_paise(self) -> int:
        return sum(row.closing_credit_paise for row in self.rows)

    @property
    def balances(self) -> bool:
        """It always should. If it does not, something bypassed the journal."""
        return self.total_debit_paise == self.total_credit_paise


@dataclass(frozen=True)
class ProfitAndLoss:
    income: tuple[LedgerBalance, ...]
    expenses: tuple[LedgerBalance, ...]
    footer: ReportFooter

    @property
    def total_income_paise(self) -> int:
        return sum(-row.net_paise for row in self.income)

    @property
    def total_expenses_paise(self) -> int:
        return sum(row.net_paise for row in self.expenses)

    @property
    def net_profit_paise(self) -> int:
        """Positive is a profit, negative a loss."""
        return self.total_income_paise - self.total_expenses_paise


@dataclass(frozen=True)
class BalanceSheet:
    assets: tuple[LedgerBalance, ...]
    liabilities: tuple[LedgerBalance, ...]
    net_profit_paise: int
    footer: ReportFooter
    #: Anything sitting in Suspense. Not an error, but a balance sheet with a
    #: suspense figure on it is a balance sheet with a question on it.
    suspense_paise: int = 0

    @property
    def total_assets_paise(self) -> int:
        return sum(row.net_paise for row in self.assets)

    @property
    def total_liabilities_paise(self) -> int:
        return sum(-row.net_paise for row in self.liabilities)

    @property
    def total_liabilities_and_profit_paise(self) -> int:
        """The figure that must equal total assets: liabilities plus the year's result."""
        return self.total_liabilities_paise + self.net_profit_paise

    @property
    def balances(self) -> bool:
        return self.total_assets_paise == self.total_liabilities_and_profit_paise


# ---------------------------------------------------------------------------
# Building them
# ---------------------------------------------------------------------------


def trial_balance(client, financial_year: int) -> TrialBalance:
    rows, footer = _balances(client, financial_year)
    return TrialBalance(rows=rows, footer=footer)


def profit_and_loss(client, financial_year: int) -> ProfitAndLoss:
    rows, footer = _balances(client, financial_year)
    return ProfitAndLoss(
        income=tuple(r for r in rows if r.group in INCOME_GROUPS),
        expenses=tuple(
            r for r in rows if r.is_profit_and_loss and r.group not in INCOME_GROUPS
        ),
        footer=footer,
    )


def balance_sheet(client, financial_year: int) -> BalanceSheet:
    rows, footer = _balances(client, financial_year)
    trading = ProfitAndLoss(
        income=tuple(r for r in rows if r.group in INCOME_GROUPS),
        expenses=tuple(
            r for r in rows if r.is_profit_and_loss and r.group not in INCOME_GROUPS
        ),
        footer=footer,
    )
    standing = [r for r in rows if not r.is_profit_and_loss]

    return BalanceSheet(
        assets=tuple(r for r in standing if r.group in ASSET_GROUPS),
        liabilities=tuple(
            r for r in standing if r.group not in ASSET_GROUPS and r.group != LedgerGroup.SUSPENSE
        ),
        net_profit_paise=trading.net_profit_paise,
        suspense_paise=sum(
            r.net_paise for r in standing if r.group == LedgerGroup.SUSPENSE
        ),
        footer=footer,
    )


#: Tally's own names for the two balancing lines, so a CA reads them as familiar.
PROFIT_BROUGHT_FORWARD = "Profit & Loss A/c"
OPENING_DIFFERENCE = "Difference in opening balances"


def _balances(client, financial_year: int) -> tuple[tuple[LedgerBalance, ...], ReportFooter]:
    """Every ledger's position at the end of ``financial_year``.

    Balance-sheet ledgers carry their whole history into the year; income and
    expense ledgers do not, and their earlier years' results arrive as a single
    Profit & Loss A/c balance instead. Confirmed bank opening balances are added
    to the bank ledgers, and since nothing else's opening balance is known, their
    counterpart is shown -- as Tally shows it -- as a difference in opening
    balances for a CA to allocate, usually to capital. Every line posted up to
    the year end nets to zero, so the trial balance still balances.
    """
    start, end = fy_bounds(financial_year)
    in_year = Q(entry__entry_date__gte=start)

    aggregated = (
        JournalLine.objects.filter(
            firm_id=client.firm_id,
            entry__client=client,
            entry__entry_date__lte=end,
        )
        .values("ledger_account__name", "ledger_account__group")
        .annotate(
            debit=Sum("amount_paise", filter=Q(direction="DR") & in_year),
            credit=Sum("amount_paise", filter=Q(direction="CR") & in_year),
            before=Sum("signed_paise", filter=Q(entry__entry_date__lt=start)),
        )
    )

    balances: dict[str, dict] = {}
    earlier_results = 0
    for row in aggregated:
        group = row["ledger_account__group"]
        before = row["before"] or 0
        if group in PROFIT_AND_LOSS_GROUPS:
            earlier_results += before
            before = 0
        balances[row["ledger_account__name"]] = {
            "group": group,
            "debit": row["debit"] or 0,
            "credit": row["credit"] or 0,
            "opening": before,
        }

    confirmed_openings = 0
    for account in client.bank_accounts.filter(opening_balance_paise__isnull=False):
        if account.opening_as_of and account.opening_as_of > end:
            continue
        name = account.ledger_name
        entry = balances.setdefault(name, {"group": LedgerGroup.BANK, "debit": 0, "credit": 0, "opening": 0})
        entry["opening"] += account.opening_balance_paise
        confirmed_openings += account.opening_balance_paise

    for name, opening in ((PROFIT_BROUGHT_FORWARD, earlier_results), (OPENING_DIFFERENCE, -confirmed_openings)):
        if opening:
            balances[name] = {"group": LedgerGroup.CAPITAL, "debit": 0, "credit": 0, "opening": opening}

    rows = tuple(
        sorted(
            (
                LedgerBalance(
                    name=name,
                    group=values["group"],
                    debit_paise=values["debit"],
                    credit_paise=values["credit"],
                    opening_paise=values["opening"],
                )
                for name, values in balances.items()
                if values["debit"] or values["credit"] or values["opening"]
            ),
            key=lambda r: (r.group, r.name),
        )
    )
    return rows, _footer(client, financial_year, start, end)


def _footer(client, financial_year: int, start, end) -> ReportFooter:
    from classify.engine import review_queue
    from ledger.models import JournalEntry

    entry_count = JournalEntry.objects.filter(
        firm_id=client.firm_id, client=client, entry_date__gte=start, entry_date__lte=end
    ).count()

    pending = review_queue(client).filter(
        transaction__value_date__gte=start, transaction__value_date__lte=end
    ).count()

    return ReportFooter(
        client_name=client.name,
        financial_year=financial_year,
        period_start=start,
        period_end=end,
        entry_count=entry_count,
        pending_review=pending,
        generated_at=timezone.now(),
    )


def render_trial_balance(report: TrialBalance) -> str:
    """A plain-text trial balance, in the shape a firm already reads."""
    width = max((len(row.name) for row in report.rows), default=20)
    lines = [
        f"{'Particulars'.ljust(width)}  {'Debit':>16}  {'Credit':>16}",
        "-" * (width + 36),
    ]
    for row in report.rows:
        lines.append(
            f"{row.name.ljust(width)}  "
            f"{format_inr(row.closing_debit_paise) if row.closing_debit_paise else '':>16}  "
            f"{format_inr(row.closing_credit_paise) if row.closing_credit_paise else '':>16}"
        )
    lines.append("-" * (width + 36))
    lines.append(
        f"{'Total'.ljust(width)}  {format_inr(report.total_debit_paise):>16}  "
        f"{format_inr(report.total_credit_paise):>16}"
    )
    lines.append("")
    lines.append(report.footer.caption())
    return "\n".join(lines)
