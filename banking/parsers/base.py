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
from decimal import Decimal, InvalidOperation

from integrations.pdf.base import PdfDocument

ZERO = Decimal("0.00")


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


def parse_amount(raw: str | None) -> Decimal | None:
    """Parse an Indian-format money cell. ``None`` for an empty cell.

    Handles ``1,00,000.00`` (lakh grouping), a trailing ``Cr``/``Dr`` marker,
    and unicode minus. Refuses anything else rather than guessing -- a cell that
    does not look like money is a sign the column mapping is wrong, and that is
    exactly the bug the balance chain exists to catch early.
    """
    if raw is None:
        return None
    text = raw.strip().replace("\n", " ")
    if not text or text in {"-", "--"}:
        return None

    text = text.replace("−", "-").replace(",", "").replace(" ", "")
    sign = Decimal(1)
    upper = text.upper()
    for marker in ("CR", "DR"):
        if upper.endswith(marker):
            text = text[: -len(marker)]
            if marker == "DR":
                sign = Decimal(-1)
            break
    if text.startswith("(") and text.endswith(")"):
        text, sign = text[1:-1], Decimal(-1)

    try:
        return (Decimal(text) * sign).quantize(ZERO)
    except (InvalidOperation, ValueError) as exc:
        raise StatementParseError(f"Not a money value: {raw!r}") from exc


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
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    balance: Decimal = ZERO
    cheque_number: str = ""
    branch_code: str = ""

    def __post_init__(self):
        if self.debit < 0 or self.credit < 0:
            raise StatementParseError(
                f"Row {self.row_number}: negative amount "
                f"(debit={self.debit}, credit={self.credit}). Direction is "
                f"carried by which column the amount is in, not by its sign."
            )
        if self.debit and self.credit:
            raise StatementParseError(
                f"Row {self.row_number}: amounts in both the debit and credit "
                f"columns ({self.debit} / {self.credit}). The column mapping is "
                f"wrong, or the row is a summary line that should not be here."
            )
        if not self.debit and not self.credit:
            raise StatementParseError(
                f"Row {self.row_number}: no amount in either column. A zero-value "
                f"transaction is not a thing; this is a header or total row that "
                f"the parser failed to recognise."
            )

    @property
    def is_debit(self) -> bool:
        """True when money left the account."""
        return self.debit > 0

    @property
    def amount(self) -> Decimal:
        return self.debit if self.is_debit else self.credit

    @property
    def signed_amount(self) -> Decimal:
        """Effect on the balance: negative for money out."""
        return self.credit - self.debit


@dataclass(frozen=True)
class ParsedStatement:
    """A statement that has been read *and proved*.

    Constructing one is the proof. See the module docstring.
    """

    bank_code: str
    account_number: str
    period_start: datetime.date
    period_end: datetime.date
    opening_balance: Decimal
    closing_balance: Decimal
    transactions: tuple[ParsedTransaction, ...] = field(default_factory=tuple)
    account_holder: str = ""
    ifsc: str = ""
    #: The statement's own footer totals, when it prints them. A second,
    #: independent check: the chain can only be reproduced by getting every row
    #: right, but these catch a compensating pair of errors.
    stated_total_debit: Decimal | None = None
    stated_total_credit: Decimal | None = None

    def __post_init__(self):
        self._check_balance_chain()
        self._check_stated_totals()
        self._check_period()

    # -- the gate -----------------------------------------------------------

    def _check_balance_chain(self) -> None:
        running = self.opening_balance
        for txn in self.transactions:
            running += txn.signed_amount
            if running != txn.balance:
                raise BalanceChainError(
                    f"Balance chain broke at row {txn.row_number} "
                    f"({txn.date:%d-%m-%Y}, {collapse_whitespace(txn.narration)[:60]!r}): "
                    f"expected a balance of {running} after applying "
                    f"{txn.signed_amount:+}, but the statement prints {txn.balance}. "
                    f"A row was dropped, duplicated, or read into the wrong column "
                    f"at or before this point."
                )
        if running != self.closing_balance:
            raise BalanceChainError(
                f"Statement does not close: {len(self.transactions)} rows take "
                f"the opening balance of {self.opening_balance} to {running}, but "
                f"the statement prints a closing balance of {self.closing_balance}. "
                f"Rows are missing from the end, most likely a final page that "
                f"was not extracted."
            )

    def _check_stated_totals(self) -> None:
        if self.stated_total_debit is not None and self.total_debit != self.stated_total_debit:
            raise BalanceChainError(
                f"Debit total mismatch: rows sum to {self.total_debit}, statement "
                f"footer says {self.stated_total_debit}."
            )
        if self.stated_total_credit is not None and self.total_credit != self.stated_total_credit:
            raise BalanceChainError(
                f"Credit total mismatch: rows sum to {self.total_credit}, statement "
                f"footer says {self.stated_total_credit}."
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
    def total_debit(self) -> Decimal:
        return sum((t.debit for t in self.transactions), ZERO)

    @property
    def total_credit(self) -> Decimal:
        return sum((t.credit for t in self.transactions), ZERO)

    def __len__(self) -> int:
        return len(self.transactions)


class StatementParser(abc.ABC):
    """One implementation per bank format."""

    #: Short stable identifier, stored on every row this parser produces.
    bank_code: str = ""

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
