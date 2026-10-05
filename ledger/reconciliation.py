"""The month-end check: does the ledger agree with the bank?

The single most valuable check in the system, and the cheapest. Everything else
verifies that a step did what it was told; this verifies that the *result* is
right. A statement can parse perfectly, classify plausibly and post cleanly, and
still leave a client's bank ledger disagreeing with their bank -- because a row
was posted twice, or a correction reversed the wrong side, or an entry was
approved against the wrong account.

Comparing the two closing figures catches all of that in one subtraction, and
it is the same subtraction the firm already does by hand today.

A mismatch blocks the period from being marked reviewed. That is deliberate:
a period that does not reconcile is not finished, and letting it be signed off
anyway makes the check decorative.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db.models import Sum

from banking.models import Statement
from classify.seeds import contra_ledger_for
from core.money import format_inr
from ledger.models import JournalLine


@dataclass(frozen=True)
class BalanceCheck:
    """One account, one date, and whether the two sides agree."""

    bank_account: object
    as_of: datetime.date
    #: What the client's books say the bank balance is.
    ledger_balance_paise: int
    #: What the bank's own statement says it is.
    statement_balance_paise: int
    #: Entries not yet approved that fall on or before ``as_of``. A mismatch
    #: with work still in the queue usually means "not finished", not "wrong",
    #: and saying which saves a pointless hunt.
    unapproved_count: int = 0

    @property
    def difference_paise(self) -> int:
        return self.ledger_balance_paise - self.statement_balance_paise

    @property
    def matches(self) -> bool:
        return self.difference_paise == 0

    @property
    def can_close(self) -> bool:
        """A period is finished when it reconciles and nothing is outstanding."""
        return self.matches and self.unapproved_count == 0

    def explain(self) -> str:
        if self.can_close:
            return (
                f"{self.bank_account} reconciles at {self.as_of:%d-%m-%Y}: "
                f"{format_inr(self.statement_balance_paise)}."
            )
        if self.matches:
            return (
                f"{self.bank_account} reconciles at {self.as_of:%d-%m-%Y}, but "
                f"{self.unapproved_count} transaction(s) up to that date are still "
                f"not posted. The period is not finished."
            )
        return (
            f"{self.bank_account} does not reconcile at {self.as_of:%d-%m-%Y}. The books "
            f"say {format_inr(self.ledger_balance_paise)}; the bank says "
            f"{format_inr(self.statement_balance_paise)}; the difference is "
            f"{format_inr(self.difference_paise)}. "
            + (
                f"{self.unapproved_count} transaction(s) up to that date have not been "
                f"posted, which is the likeliest cause."
                if self.unapproved_count
                else (
                    "The bank account's opening balance has not been confirmed, which is "
                    "the likeliest cause: the books start from nothing, not from the "
                    "balance the bank had."
                    if not self.bank_account.has_opening_balance
                    else "Everything up to that date is posted, so this is a real break."
                )
            )
        )


def check_balance(bank_account, as_of: datetime.date) -> BalanceCheck:
    """Compare the bank ledger's computed balance to the statement's own figure."""
    statement = _statement_covering(bank_account, as_of)
    if statement is None:
        raise NoStatementError(
            f"No statement for {bank_account} covers {as_of:%d-%m-%Y}, so there is "
            f"nothing to reconcile against. Upload the period first."
        )

    return BalanceCheck(
        bank_account=bank_account,
        as_of=as_of,
        ledger_balance_paise=ledger_balance(bank_account, as_of),
        statement_balance_paise=_statement_balance_at(statement, as_of),
        unapproved_count=_unapproved_up_to(bank_account, as_of),
    )


def ledger_balance(bank_account, as_of: datetime.date) -> int:
    """The bank ledger's balance from the journal, plus the opening balance.

    Debits increase a bank balance and credits decrease it, which is what
    ``signed_paise`` already encodes -- so this is a sum, not a case expression.

    The opening balance is included because it is real money the client had
    before this system saw anything. A client onboarding mid-year whose opening
    balance was never confirmed will not reconcile, and should not.
    """
    ledger_account = contra_ledger_for(bank_account)
    posted = JournalLine.objects.filter(
        firm_id=bank_account.firm_id,
        ledger_account=ledger_account,
        entry__entry_date__lte=as_of,
        # A superseded entry has been reversed by its correction, and both are
        # in the ledger. Including them is correct: together they net to the
        # corrected position, which is the whole point of correcting that way.
    ).aggregate(total=Sum("signed_paise"))["total"] or 0

    if bank_account.kind == "LOAN":
        # A loan's ledger is a liability: what is owed shows as a credit, which is negative here, while the
        # statement prints it as a positive balance. Compare owed with owed.
        return (bank_account.opening_balance_paise or 0) - posted
    return (bank_account.opening_balance_paise or 0) + posted


class NoStatementError(RuntimeError):
    """Nothing on file covers the date being reconciled."""


def _statement_covering(bank_account, as_of: datetime.date):
    return (
        Statement.objects.filter(
            firm_id=bank_account.firm_id,
            bank_account=bank_account,
            period_start__lte=as_of,
            period_end__gte=as_of,
        )
        .order_by("-period_end")
        .first()
    )


def _statement_balance_at(statement, as_of: datetime.date) -> int:
    """The running balance the bank printed on or before ``as_of``.

    The statement's own closing figure when the date is its period end;
    otherwise the balance after the last transaction up to that date, which is
    the same number the bank would print on a statement cut there.
    """
    if as_of >= statement.period_end:
        return statement.closing_balance_paise

    last = (
        statement.transactions.filter(value_date__lte=as_of)
        .order_by("value_date", "row_number")
        .last()
    )
    return last.balance_paise if last else statement.opening_balance_paise


def _unapproved_up_to(bank_account, as_of: datetime.date) -> int:
    from classify.engine import review_queue

    return review_queue(bank_account.client).filter(
        transaction__bank_account=bank_account, transaction__value_date__lte=as_of
    ).count()
