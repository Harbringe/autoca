"""Statement parsing contract, and the arithmetic gate every parser passes.

A bank statement is one of the few documents in accounting that carries its own
proof. Every row states the balance after it, the header states the balance
before the first row, and the footer states the balance after the last one. So
a parse either reconstructs that chain exactly or it is wrong -- there is no
middle state where the output is "mostly right".

That is worth leaning on hard, because the failure modes of PDF parsing are all
silent:

* a row is dropped because it straddled a page break;
* a debit is read as a credit because the amount landed in the wrong cell;
* a continuation line of narration is mistaken for a row of its own;
* ``1,00,000.00`` loses a digit to a careless separator strip.

None of these raise. All of them break the chain. So :class:`ParsedStatement`
validates the chain in ``__post_init__`` and **refuses to exist** when it does
not tie out, exactly as :class:`~integrations.ocr.base.OCRResult` refuses to
exist when pages went missing. A caller cannot forget to check, because there
is no object to check.

The practical effect: this codebase can accept a new bank's format without a
human eyeballing the output. Either it balances or it raises with the row
number where the arithmetic first went wrong.
"""

from __future__ import annotations

import abc
import datetime
import re
from dataclasses import dataclass, field

from core.money import MoneyError, format_inr, to_paise
from integrations.pdf.base import PdfDocument


class StatementParseError(RuntimeError):
    """The document is not a statement this parser can read."""


class UnsupportedBankError(StatementParseError):
    """No registered parser recognised the document."""


class BalanceChainError(StatementParseError):
    """The parsed rows do not reproduce the statement's own balances.

    Always a parser bug or a doctored document, never a user error. The message
    names the first row where the running balance diverged, which is almost
    always the row whose layout the parser mishandled.
    """


class NoTextLayerError(StatementParseError):
    """A scanned statement. OCR is the fallback path and is not wired yet."""


def parse_amount(raw: str | None) -> int | None:
    """Parse an Indian-format money cell to whole paise. ``None`` if empty.

    Handles ``1,00,000.00`` lakh grouping and a trailing ``Cr``/``Dr`` marker.
    Refuses anything else rather than guessing -- a cell that does not look like
    money means the column mapping is wrong, and catching that here is far
    cheaper than catching it three steps downstream.
    """
    if raw is None:
        return None
    text = collapse_whitespace(raw)
    if not text or text in {"-", "--"}:
        return None
    try:
        return to_paise(text)
    except MoneyError as exc:
        raise StatementParseError(str(exc)) from exc


def parse_date(raw: str | None, formats=("%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y")):
    """Parse a statement date cell, or return ``None`` if it is not a date.

    Day-first throughout: every Indian bank statement is ``dd-mm-yyyy``, and
    guessing between that and ``mm-dd-yyyy`` silently reorders a financial year.
    """
    if raw is None:
        return None
    text = raw.strip().replace("\n", " ")
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def collapse_whitespace(text: str) -> str:
    """Narration as one line, with the bank's line wrapping removed.

    The wrap position is a rendering artefact of the column width and carries no
    information, but it does break every downstream string match if it is kept.
    """
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


@dataclass(frozen=True)
class ParsedTransaction:
    """One row of the statement table."""

    row_number: int
    date: datetime.date
    narration: str
    debit_paise: int = 0
    credit_paise: int = 0
    balance_paise: int = 0
    cheque_number: str = ""
    branch_code: str = ""

    def __post_init__(self):
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise StatementParseError(
                f"Row {self.row_number}: negative amount "
                f"(debit={self.debit_paise}, credit={self.credit_paise}). Direction "
                f"is carried by which column the amount is in, not by its sign."
            )
        if self.debit_paise and self.credit_paise:
            raise StatementParseError(
                f"Row {self.row_number}: amounts in both the debit and credit "
                f"columns ({format_inr(self.debit_paise)} / "
                f"{format_inr(self.credit_paise)}). The column mapping is wrong, or "
                f"the row is a summary line that should not be here."
            )
        if not self.debit_paise and not self.credit_paise:
            raise StatementParseError(
                f"Row {self.row_number}: no amount in either column. A zero-value "
                f"transaction is not a thing; this is a header or total row that "
                f"the parser failed to recognise."
            )

    @property
    def is_debit(self) -> bool:
        """True when money left the account."""
        return self.debit_paise > 0

    @property
    def amount_paise(self) -> int:
        return self.debit_paise if self.is_debit else self.credit_paise

    @property
    def signed_paise(self) -> int:
        """Effect on the balance: negative for money out."""
        return self.credit_paise - self.debit_paise


@dataclass(frozen=True)
class ParsedStatement:
    """A statement that has been read *and proved*.

    Constructing one is the proof. See the module docstring.
    """

    bank_code: str
    account_number: str
    period_start: datetime.date
    period_end: datetime.date
    opening_balance_paise: int
    closing_balance_paise: int
    transactions: tuple[ParsedTransaction, ...] = field(default_factory=tuple)
    account_holder: str = ""
    ifsc: str = ""
    #: The statement's own footer totals, when it prints them. A second,
    #: independent check: the chain can only be reproduced by getting every row
    #: right, but these catch a compensating pair of errors.
    stated_total_debit_paise: int | None = None
    stated_total_credit_paise: int | None = None

    def __post_init__(self):
        self._check_balance_chain()
        self._check_stated_totals()
        self._check_period()

    # -- the gate -----------------------------------------------------------

    def _check_balance_chain(self) -> None:
        running = self.opening_balance_paise
        for txn in self.transactions:
            running += txn.signed_paise
            if running != txn.balance_paise:
                raise BalanceChainError(
                    f"Balance chain broke at row {txn.row_number} "
                    f"({txn.date:%d-%m-%Y}, {collapse_whitespace(txn.narration)[:60]!r}): "
                    f"expected a balance of {format_inr(running)} after applying "
                    f"{format_inr(txn.signed_paise)}, but the statement prints "
                    f"{format_inr(txn.balance_paise)}. A row was dropped, duplicated, "
                    f"or read into the wrong column at or before this point."
                )
        if running != self.closing_balance_paise:
            raise BalanceChainError(
                f"Statement does not close: {len(self.transactions)} rows take the "
                f"opening balance of {format_inr(self.opening_balance_paise)} to "
                f"{format_inr(running)}, but the statement prints a closing balance "
                f"of {format_inr(self.closing_balance_paise)}. Rows are missing from "
                f"the end, most likely a final page that was not extracted."
            )

    def _check_stated_totals(self) -> None:
        stated_debit = self.stated_total_debit_paise
        if stated_debit is not None and self.total_debit_paise != stated_debit:
            raise BalanceChainError(
                f"Debit total mismatch: rows sum to {format_inr(self.total_debit_paise)}, "
                f"statement footer says {format_inr(stated_debit)}."
            )
        stated_credit = self.stated_total_credit_paise
        if stated_credit is not None and self.total_credit_paise != stated_credit:
            raise BalanceChainError(
                f"Credit total mismatch: rows sum to {format_inr(self.total_credit_paise)}, "
                f"statement footer says {format_inr(stated_credit)}."
            )

    def _check_period(self) -> None:
        if self.period_end < self.period_start:
            raise StatementParseError(
                f"Statement period runs backwards: {self.period_start} to {self.period_end}."
            )
        outside = [t for t in self.transactions if not self.period_start <= t.date <= self.period_end]
        if outside:
            first = outside[0]
            raise StatementParseError(
                f"Row {first.row_number} is dated {first.date:%d-%m-%Y}, outside the "
                f"statement period {self.period_start:%d-%m-%Y} to "
                f"{self.period_end:%d-%m-%Y}. Usually a day/month swap in the date "
                f"format, which would silently reorder the financial year."
            )

    # -- derived ------------------------------------------------------------

    @property
    def total_debit_paise(self) -> int:
        return sum(t.debit_paise for t in self.transactions)

    @property
    def total_credit_paise(self) -> int:
        return sum(t.credit_paise for t in self.transactions)

    def __len__(self) -> int:
        return len(self.transactions)


class StatementParser(abc.ABC):
    """One implementation per bank format."""

    #: Short stable identifier, stored on every row this parser produces.
    bank_code: str = ""

    #: Bump on any change that could alter this parser's output. Recorded on
    #: each statement, so a parser bug can be re-run against exactly the
    #: statements it touched instead of against everything, or against a list
    #: someone kept by hand and forgot to update.
    version: int = 1

    @classmethod
    @abc.abstractmethod
    def detect(cls, document: PdfDocument) -> bool:
        """True if this parser recognises the document as its own format."""

    @abc.abstractmethod
    def parse(self, document: PdfDocument) -> ParsedStatement:
        """Read the document, or raise :class:`StatementParseError`."""

    @property
    def name(self) -> str:
        return type(self).__name__
