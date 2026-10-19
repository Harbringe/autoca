"""A statement whose rows are not a ruled table, read by where each word sits on the page.

Some banks (HDFC's e-statement is one) print the transactions as a single block per page: the table extractor then returns one
cell per column holding every row's text joined by line breaks, so there is nothing per row to read. The page's words and where
they sit are still there, and that is enough:

* **The header names the columns.** A line carrying a date, a debit (withdrawal), a credit (deposit) and a balance column is the
  header; the wording is matched the way the table reader matches it (``columns.HEADER_ALIASES``), so ``WithdrawalAmt.`` and
  ``Closing Balance`` are read, and ``Value Dt`` is told apart from the transaction date.
* **A row starts with a date** at the left of the page. The lines under it, until the next date, are the rest of that row: the
  narration wraps over several lines, and the amounts may be on the first line or a later one.
* **Money is told from text by position.** A figure at or right of the money columns is an amount or the balance; the same digits
  inside a narration are not. An amount is a withdrawal or a deposit by which header it sits nearest, measured on either edge
  because banks right-align or centre figures under a header.
* **Lines at the top of a page, under the header, are the end of the last row of the page before.** Lines after the last row that
  are set well apart from it (a footer) are not.
* **The statement's own summary is the proof, when it prints one.** Opening and closing balance, how many debits and credits, and
  their totals are read from it and checked against what was read. Without one, the running balance of every row is the proof.

Nothing here decides a figure by itself: every row has to carry the balance after it, and ``ParsedStatement`` refuses to exist
unless the opening balance, every row and the closing balance follow from one another. A column read wrongly breaks that on the
first row it touches, so it is refused, not misread.

Not read: a statement with one amount column and a separate Dr/Cr flag, a header split over two lines, or a scan. Those are refused
as before, with the reason.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from integrations.pdf.base import PdfDocument, PdfLine, PdfWord

from .base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    collapse_whitespace,
)
from .columns import HEADER_ALIASES, as_date, as_paise, normalise_header
from .generic import UNKNOWN_HOLDER, GenericStatementParser
from .icici import order_within_days

#: Header wording -> role. The transaction date and the value date are told apart: only the first is a row's date.
_ALIASES = {**HEADER_ALIASES, "valuedate": "value", "valuedt": "value", "valdate": "value"}

_MONEY = re.compile(r"^-?\d[\d,]*\.\d{2}$")

#: A date's first word may start this far right of the date header's right edge (dates are left-aligned under a centred title).
DATE_SLACK = 10.0
#: How far left of the first money header a long amount may start.
MONEY_MARGIN = 14.0
#: How far a reference or value date may sit outside its header's width.
BAND_SLACK = 12.0
#: A line further below the one before than this many line heights is not the end of a row (it is a footer).
GAP_LINES = 2.0
#: Rows read from the first pages are enough to say the layout is this one.
DETECT_PAGES = 6
#: A row dated this many days outside the printed period is the bank's own (interest dated the day after year end), not a misread.
PERIOD_SLACK_DAYS = 7

_SUMMARY_KEYS = {
    "openingbalance": "opening",
    "openingbal": "opening",
    "closingbalance": "closing",
    "closingbal": "closing",
    "drcount": "dr_count",
    "debitcount": "dr_count",
    "crcount": "cr_count",
    "creditcount": "cr_count",
    "debits": "debits",
    "totaldebits": "debits",
    "totaldebit": "debits",
    "withdrawals": "debits",
    "credits": "credits",
    "totalcredits": "credits",
    "totalcredit": "credits",
    "deposits": "credits",
}
_STOPS = ("statementsummary", "generatedon", "computergenerated", "registeredoffice")


@dataclass(frozen=True)
class _Columns:
    date: tuple[float, float]
    debit: tuple[float, float]
    credit: tuple[float, float]
    balance: tuple[float, float]
    reference: tuple[float, float] | None = None
    value: tuple[float, float] | None = None

    @property
    def money_start(self) -> float:
        return min(self.debit[0], self.credit[0], self.balance[0]) - MONEY_MARGIN


@dataclass
class _Group:
    """One row as read: its date and the words of the lines that belong to it."""

    date: datetime.date
    lines: list[tuple[PdfLine, int]] = field(default_factory=list)  # (line, how many leading words are the date)
    tail: list[PdfLine] = field(default_factory=list)  # lines carried over from the top of the next page


def _read_header(line: PdfLine) -> _Columns | None:
    words = line.words
    roles: dict[str, tuple[float, float]] = {}
    i = 0
    while i < len(words):
        pair = normalise_header(words[i].text + words[i + 1].text) if i + 1 < len(words) else ""
        single = normalise_header(words[i].text)
        if pair in _ALIASES:
            key, span = pair, 2
        elif single in _ALIASES:
            key, span = single, 1
        else:
            i += 1
            continue
        roles.setdefault(_ALIASES[key], (words[i].x0, words[i + span - 1].x1))
        i += span
    if {"date", "debit", "credit", "balance"} <= roles.keys():
        return _Columns(
            date=roles["date"], debit=roles["debit"], credit=roles["credit"], balance=roles["balance"],
            reference=roles.get("reference"), value=roles.get("value"),
        )
    return None


def _is_money(word: PdfWord, cols: _Columns) -> bool:
    return bool(_MONEY.match(word.text)) and word.x0 >= cols.money_start


def _leading_date(line: PdfLine, cols: _Columns):
    """The date a line starts with and how many words it takes, or None."""
    words = line.words
    if not words or words[0].x0 > cols.date[1] + DATE_SLACK or words[0].x0 >= cols.money_start:
        return None
    for take in (1, 2, 3):
        if take > len(words):
            break
        found = as_date(" ".join(w.text for w in words[:take]))
        if found:
            return found, take
    return None


def _norm(line: PdfLine) -> str:
    return normalise_header(line.text)


def _is_stop(line: PdfLine) -> bool:
    text = _norm(line)
    return any(s in text for s in _STOPS) or ("openingbalance" in text and "closingbal" in text)


def _gap(word: PdfWord, header: tuple[float, float]) -> float:
    """How far a figure sits from a header: the nearest of the right edges, the centres and the left edges."""
    return min(abs(word.x1 - header[1]), abs(word.centre - (header[0] + header[1]) / 2), abs(word.x0 - header[0]))


def _in_band(word: PdfWord, band: tuple[float, float] | None) -> bool:
    return band is not None and band[0] - BAND_SLACK <= word.x0 <= band[1] + BAND_SLACK


def _pitch(lines: list[PdfLine]) -> float:
    """The height of one printed line on this page: the smallest real step between lines."""
    steps = [b.top - a.top for a, b in zip(lines, lines[1:], strict=False) if b.top - a.top > 3]
    return min(steps) if steps else 12.0


class PositionalStatementParser(StatementParser):
    """Rows rebuilt from word positions, for a statement the table reader finds no rows in."""

    #: The same code as the table reader: the account is the same account whichever reader found its rows.
    bank_code = "GENERIC"
    version = 2

    MIN_ROWS = 3

    def __init__(self, *, liability: bool = False):
        #: A loan statement (decided by the caller from the title): the balance rises with a debit.
        self.liability = liability

    # -- detection -------------------------------------------------------------

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        groups, cols = cls._collect(document, limit_pages=DETECT_PAGES)
        if cols is None:
            return False
        return sum(1 for g in groups if len(cls._money_of(g, cols)) == 2) >= cls.MIN_ROWS

    # -- reading ---------------------------------------------------------------

    @classmethod
    def _collect(cls, document: PdfDocument, limit_pages: int | None = None):
        cols: _Columns | None = None
        groups: list[_Group] = []
        pages = document.pages if limit_pages is None else document.pages[:limit_pages]
        for page in pages:
            lines = list(page.lines)
            header_at = next((i for i, line in enumerate(lines) if _read_header(line) is not None), None)
            if header_at is not None:
                cols = _read_header(lines[header_at])
            if cols is None:
                continue
            start = header_at + 1 if header_at is not None else 0
            region: list[PdfLine] = []
            for line in lines[start:]:
                if _is_stop(line):
                    break
                region.append(line)
            pitch = _pitch(region if header_at is None else lines[header_at:header_at + 1] + region)
            previous_top = lines[header_at].top if header_at is not None else None
            current: _Group | None = None
            row_seen = False
            for line in region:
                led = _leading_date(line, cols)
                close = previous_top is not None and line.top - previous_top <= pitch * GAP_LINES
                if led is not None:
                    current = _Group(date=led[0])
                    current.lines.append((line, led[1]))
                    groups.append(current)
                    row_seen = True
                elif current is not None:
                    if close:
                        current.lines.append((line, 0))
                    else:
                        current = None  # a footer or a new block, not the rest of the row
                elif not row_seen and header_at is not None and groups and close:
                    # Between this page's header and its first row: the end of the last row of the page before.
                    groups[-1].tail.append(line)
                previous_top = line.top
        return groups, cols

    @staticmethod
    def _money_of(group: _Group, cols: _Columns) -> list[PdfWord]:
        """The figures in the money columns on the lines that are this row's own (not the carried-over tail)."""
        return [w for line, skip in group.lines for w in line.words[skip:] if _is_money(w, cols)]

    def parse(self, document: PdfDocument) -> ParsedStatement:
        groups, cols = self._collect(document)
        if cols is None or not groups:
            raise StatementParseError("No transaction rows were found by their position on the page.")
        rows, markers = self._rows(groups, cols)
        if len(rows) < self.MIN_ROWS:
            raise StatementParseError(f"Found only {len(rows)} transaction-shaped row(s) by position. This is not a bank statement, or its rows were not readable.")

        summary = self._summary(document)
        rows = order_within_days(rows)
        for number, row in enumerate(rows, start=1):
            row["number"] = number
        transactions = [
            ParsedTransaction(
                row_number=row["number"], date=row["date"], narration=row["narration"],
                debit_paise=row["amount"] if row["signed"] < 0 else 0, credit_paise=row["amount"] if row["signed"] > 0 else 0,
                balance_paise=row["balance"], cheque_number=row["cheque"],
            )
            for row in rows
        ]
        self._check_markers(rows, markers)
        self._check_counts(transactions, summary)

        opening = summary.get("opening")
        if opening is None:
            opening = markers[0][1] if markers and markers[0][0] == 0 else rows[0]["balance"] - rows[0]["effect"]
        closing = summary.get("closing")
        if closing is None:
            closing = transactions[-1].balance_paise

        text = document.text
        printed = GenericStatementParser._printed_period(text)
        first, last = min(t.date for t in transactions), max(t.date for t in transactions)
        start, end = first, last
        if printed:
            slack = datetime.timedelta(days=PERIOD_SLACK_DAYS)
            start = min(printed[0], first) if first >= printed[0] - slack else printed[0]
            end = max(printed[1], last) if last <= printed[1] + slack else printed[1]
        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=GenericStatementParser._account_number(text),
            account_holder=UNKNOWN_HOLDER,
            ifsc=GenericStatementParser._ifsc(text),
            period_start=start,
            period_end=end,
            opening_balance_paise=opening,
            closing_balance_paise=closing,
            transactions=tuple(transactions),
            stated_total_debit_paise=summary.get("debits"),
            stated_total_credit_paise=summary.get("credits"),
            kind="LOAN" if self.liability else "BANK",
            liability=self.liability,
        )

    def _rows(self, groups: list[_Group], cols: _Columns):
        """The groups as rows. A line of only a balance (no amount) is a marker, kept to check the chain at that point."""
        rows: list[dict] = []
        markers: list[tuple[int, int]] = []
        for group in groups:
            money: list[PdfWord] = []
            narration: list[str] = []
            reference: list[str] = []
            own = [(line, skip, True) for line, skip in group.lines]
            for line, skip, counts in [*own, *((t, 0, False) for t in group.tail)]:
                for word in line.words[skip:]:
                    if word.x0 >= cols.money_start:
                        if counts and _MONEY.match(word.text):
                            money.append(word)
                        continue  # a Dr/Cr flag or a stray mark in the money columns is not narration
                    if cols.value is not None and _in_band(word, cols.value) and as_date(word.text):
                        continue
                    if _in_band(word, cols.reference):
                        reference.append(word.text)
                    else:
                        narration.append(word.text)
            if len(money) == 1:
                markers.append((len(rows), self._paise(money[0])))
                continue
            if not money:
                continue  # a date with nothing to say; a real row lost this way breaks the balance chain
            if len(money) != 2:
                raise StatementParseError(
                    f"The row dated {group.date:%d-%m-%Y} has {len(money)} figures in the money columns; an amount and a balance were expected."
                )
            balance_word = min(money, key=lambda w: _gap(w, cols.balance))
            amount_word = money[0] if money[1] is balance_word else money[1]
            debit = _gap(amount_word, cols.debit) <= _gap(amount_word, cols.credit)
            amount = self._paise(amount_word)
            signed = -amount if debit else amount
            rows.append(
                {
                    "date": group.date,
                    "amount": abs(amount),
                    "signed": signed,
                    # What the row does to the printed balance: a loan's balance moves the other way.
                    "effect": -signed if self.liability else signed,
                    "balance": self._paise(balance_word),
                    "cheque": collapse_whitespace(" ".join(reference))[:32],
                    "narration": collapse_whitespace(" ".join(narration)),
                }
            )
        return rows, markers

    @staticmethod
    def _paise(word: PdfWord) -> int:
        value = as_paise(word.text)
        if value is None:
            raise StatementParseError(f"{word.text!r} could not be read as an amount.")
        return value

    @staticmethod
    def _check_markers(rows: list[dict], markers: list[tuple[int, int]]) -> None:
        """A balance printed on a line of its own (brought forward, carried forward) must be where the rows say it is."""
        for index, balance in markers:
            if index == 0:
                continue  # the opening: it is the proof's starting point, checked by the chain
            if rows[index - 1]["balance"] != balance:
                raise StatementParseError(
                    "A balance printed between rows does not match the rows before it, so a row is missing or misread there."
                )

    @staticmethod
    def _check_counts(transactions: list[ParsedTransaction], summary: dict) -> None:
        debits = sum(1 for t in transactions if t.is_debit)
        credits = len(transactions) - debits
        for key, found, word in (("dr_count", debits, "debits"), ("cr_count", credits, "credits")):
            if key in summary and summary[key] != found:
                raise StatementParseError(f"The statement says it has {summary[key]} {word}, but {found} were read. A row is missing or misread.")

    # -- the statement's own summary ------------------------------------------------

    @staticmethod
    def _summary(document: PdfDocument) -> dict:
        """Opening and closing balance, debit and credit counts and totals, from a summary block if the statement prints one."""
        for page in reversed(document.pages):
            lines = list(page.lines)
            for i, line in enumerate(lines[:-1]):
                keys = [(w, _SUMMARY_KEYS.get(normalise_header(w.text))) for w in line.words]
                named = [(w, k) for w, k in keys if k]
                if not {"opening", "closing"} <= {k for _, k in named}:
                    continue
                values = [w for w in lines[i + 1].words if re.match(r"^-?\d[\d,]*(\.\d{2})?$", w.text)]
                if len(values) < len(named):
                    continue
                out: dict = {}
                for word, key in named:
                    nearest = min(values, key=lambda v: abs(v.x0 - word.x0))
                    if key in ("dr_count", "cr_count"):
                        out[key] = int(nearest.text.replace(",", ""))
                    else:
                        paise = as_paise(nearest.text)
                        if paise is not None:
                            out[key] = paise
                return out
        return {}
