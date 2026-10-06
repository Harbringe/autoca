"""A statement parser that does not know which bank it is reading.

This is the path most statements will take. A dedicated parser per bank is
exact and does not scale to "any bank a client happens to use" -- a firm with
thirty clients sees a dozen banks, and a new one arrives the week after you
finish the last.

What makes a generic parser safe here is the same thing that makes the
dedicated ones safe: the statement checks the answer. Column roles are inferred
and then *proved* against the running balance (see
:mod:`banking.parsers.columns`), and the resulting rows are proved again by
:class:`~banking.parsers.base.ParsedStatement`, which refuses to exist unless
they reproduce the opening figure, every intermediate balance and the closing
figure. Two independent gates, neither of which needs a human.

A dedicated parser is still worth writing when a bank's layout defeats the
inference, or to pick up detail the generic path drops -- a branch code, a
cheque number in an oddly-named column. It earns its place by being needed, not
by being anticipated.
"""

from __future__ import annotations

import re

from integrations.pdf.base import PdfDocument

from .base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    collapse_whitespace,
)
from .columns import (
    ColumnInferenceError,
    ColumnMap,
    as_date,
    as_paise,
    infer_columns,
    normalise_header,
    signed_amount,
)

#: Rows whose narration is one of these are the statement's own arithmetic
#: rather than a transaction. Matched on the normalised narration cell.
SUMMARY_LABELS = {
    "openingbalance": "opening",
    "balancebroughtforward": "opening",
    "balancebf": "opening",
    "bfbalance": "opening",
    "bf": "opening",
    "bfwd": "opening",
    "broughtforward": "opening",
    "closingbalance": "closing",
    "balancecarriedforward": "closing",
    "balancecf": "closing",
    "cfbalance": "closing",
    "cf": "closing",
    "cfwd": "closing",
    "carriedforward": "closing",
    "transactiontotal": "totals",
    "total": "totals",
    "grandtotal": "totals",
    "pagetotal": "totals",
    "totals": "totals",
    "subtotal": "totals",
    "pagetotals": "totals",
    "closingbalancecarriedforward": "closing",
    "openingbalancebroughtforward": "opening",
    "broughtforwardfrompreviouspage": "opening",
    "carriedforwardtonextpage": "closing",
    "ctd": "totals",
}

NOT_A_CONTINUATION = re.compile(r"\bpage\b|\bof\s+\d+|statement|account|printed|continued|date\s*:", re.IGNORECASE)

ACCOUNT_NUMBER = re.compile(
    r"(?:account|a/c|acct)[^\n:]{0,24}(?:no|number|#)?[:\s.]+([0-9][0-9\s-]{6,22}[0-9])",
    re.IGNORECASE,
)
# "IFSC: HDFC0000123", "IFSC Code : ICIC0000045", "IFSC/RTGS Code - SBIN0001234".
IFSC = re.compile(
    r"IFSC(?:\s*(?:/\s*RTGS)?\s*code)?[^A-Za-z0-9]{0,6}([A-Z]{4}0[A-Z0-9]{6})",
    re.IGNORECASE,
)

#: Banks write the dates every way there is; the words around them vary less.
#: Anchored on "from" or "period", then a date, a joining word, another date.
#: Deliberately not anchored on "to" -- some statements write "01-04-2025 -
#: 30-04-2025" with no word between them at all.
_DATE = r"(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})"
PERIOD = re.compile(
    r"(?:from|period|statement\s+period)[^0-9]{0,12}" + _DATE + r"[^0-9]{1,12}" + _DATE,
    re.IGNORECASE,
)

#: Banks name the holder in wildly different places. Rather than guess, the
#: generic parser leaves it blank and lets the firm's own client record stand
#: in -- a wrong holder name would quietly break self-transfer detection, and a
#: blank one merely makes it less effective.
UNKNOWN_HOLDER = ""


class GenericStatementParser(StatementParser):
    """Reads a ruled transaction table from any bank, or refuses clearly."""

    bank_code = "GENERIC"
    version = 1

    #: Smallest table worth considering. Below this there is not enough of a
    #: balance chain to prove a column mapping against.
    MIN_ROWS = 3

    def __init__(self, *, liability: bool = False):
        #: A loan statement: the balance is what is owed, so it rises with a debit. Chosen by the caller from the
        #: document's title (see banking.parsers), never discovered here.
        self.liability = liability

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        """True when some table on some page looks like a transaction table."""
        return any(cls._candidate_rows(table) for table in document.tables())

    def parse(self, document: PdfDocument) -> ParsedStatement:
        header, rows, summaries = self._collect(document)
        continuations = self._continuations
        if len(rows) < self.MIN_ROWS:
            raise StatementParseError(
                f"Found only {len(rows)} transaction-shaped row(s). Either this "
                f"is not a bank statement, or its table was not extracted -- a "
                f"scanned page produces no table at all."
            )

        try:
            mapping = infer_columns(header, rows, liability=self.liability)
        except ColumnInferenceError as exc:
            raise StatementParseError(str(exc)) from exc

        movements, markers = self._partition(rows, mapping)
        if not movements:
            raise StatementParseError(
                "Every row in this table carries a balance but no amount, so "
                "nothing moved. This is a balance listing, not a statement."
            )

        transactions = [
            self._read_row(row, mapping, number, continuations.get(id(row), ()))
            for number, row in enumerate(movements, start=1)
        ]
        opening, closing = self._bookend_balances(
            transactions, summaries, markers, mapping, self.liability
        )
        text = document.text

        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=self._account_number(text),
            account_holder=UNKNOWN_HOLDER,
            ifsc=self._ifsc(text),
            period_start=self._period_start(text, transactions),
            period_end=self._period_end(text, transactions),
            opening_balance_paise=opening,
            closing_balance_paise=closing,
            transactions=tuple(transactions),
            kind="LOAN" if self.liability else "BANK",
            liability=self.liability,
        )

    # -- gathering rows -----------------------------------------------------

    def _collect(self, document: PdfDocument):
        """Split every table on every page into header, data rows, and summaries.

        The header is taken from the first table that has one; later pages of a
        statement usually continue the table without repeating it, and a parser
        that expected one per page would drop every page after the first.
        """
        header = None
        rows: list[list[str]] = []
        summaries: dict[str, list[list[str]]] = {}
        # A narration that wraps can come out as a row of its own: text and nothing else. It belongs to the row above.
        self._continuations: dict[int, list[str]] = {}

        for table in document.tables():
            for row in table:
                cells = [c or "" for c in row]
                if not any(c.strip() for c in cells):
                    continue

                label = self._summary_label(cells)
                if label:
                    summaries.setdefault(label, []).append(cells)
                    continue

                if self._looks_like_header(cells):
                    if header is None:
                        header = cells
                    continue

                if self._looks_like_a_transaction(cells):
                    rows.append(cells)
                elif rows and self._is_continuation(cells):
                    self._continuations.setdefault(id(rows[-1]), []).append(
                        collapse_whitespace(" ".join(c for c in cells if c.strip()))
                    )

        return header, rows, summaries

    @staticmethod
    def _is_continuation(cells) -> bool:
        """Text only: no date, no amount. The rest of a narration that did not fit on its line."""
        if any(as_date(c) for c in cells) or any(as_paise(c) is not None for c in cells):
            return False
        filled = [c for c in cells if c.strip()]
        # A page footer or a repeated title is not the end of a narration.
        return len(filled) == 1 and not NOT_A_CONTINUATION.search(filled[0])

    @classmethod
    def _candidate_rows(cls, table) -> bool:
        return sum(1 for row in table if cls._looks_like_a_transaction(row)) >= cls.MIN_ROWS

    @staticmethod
    def _looks_like_a_transaction(row) -> bool:
        """A date somewhere, and at least two numbers. Deliberately loose.

        Precision here would mean knowing the layout, which is the thing we do
        not know. Being loose is safe because the balance check downstream
        rejects anything that slipped through.
        """
        cells = [c or "" for c in row]
        has_date = any(as_date(c) for c in cells)
        numbers = sum(1 for c in cells if as_paise(c) is not None)
        return has_date and numbers >= 2

    @staticmethod
    def _looks_like_header(row) -> bool:
        from .columns import HEADER_ALIASES

        named = {
            HEADER_ALIASES[key]
            for cell in row
            if (key := normalise_header(cell)) in HEADER_ALIASES
        }
        return "balance" in named and bool(named & {"debit", "credit", "amount"})

    @staticmethod
    def _summary_label(row) -> str | None:
        for cell in row:
            key = normalise_header(cell)
            if key in SUMMARY_LABELS:
                return SUMMARY_LABELS[key]
        return None

    # -- rows into transactions ---------------------------------------------

    @staticmethod
    def _read_row(row, mapping: ColumnMap, number: int, continued=()) -> ParsedTransaction:
        date = as_date(mapping.get(row, "date"))
        if date is None:
            raise StatementParseError(
                f"Row {number} has no readable date in the column the layout "
                f"says holds one ({mapping.get(row, 'date')!r})."
            )

        signed = signed_amount(row, mapping)
        balance = as_paise(mapping.get(row, "balance"))
        if signed is None or balance is None:
            raise StatementParseError(
                f"Row {number} carries no readable amount or balance. The column "
                f"mapping was proved against the balance chain, so this row was "
                f"not part of that chain and should not have reached here."
            )

        return ParsedTransaction(
            row_number=number,
            date=date,
            narration=collapse_whitespace(" ".join([mapping.get(row, "narration"), *continued])),
            cheque_number=collapse_whitespace(mapping.get(row, "reference"))[:32],
            branch_code=collapse_whitespace(mapping.get(row, "branch"))[:16],
            debit_paise=-signed if signed < 0 else 0,
            credit_paise=signed if signed > 0 else 0,
            balance_paise=balance,
        )

    @staticmethod
    def _partition(rows, mapping: ColumnMap):
        """Split rows into things that moved money and things that only state a balance.

        A brought-forward line carries a date and a balance and no amount --
        ``B/F``, ``Opening Balance``, and every other wording a bank has thought
        of. Labelled ones are caught by name earlier; this catches the rest by
        shape, which is the only way to catch a wording nobody has seen yet.
        """
        movements, markers = [], []
        for row in rows:
            target = movements if signed_amount(row, mapping) is not None else markers
            target.append(row)
        return movements, markers

    @staticmethod
    def _bookend_balances(transactions, summaries, markers, mapping: ColumnMap, liability: bool = False):
        """Opening and closing balances, printed if the statement prints them.

        Most do, on a labelled row or a brought-forward line. The figure is read
        from the column the mapping proved is the balance -- not from "the first
        cell that looks like money", which on a statement with a serial-number
        column reads the row number and calls it the opening balance.

        When a statement prints neither, both are derived from the chain: the
        opening figure is the first row's balance less what that row did, and
        the closing figure is the last row's balance. Derived that way the outer
        check becomes a tautology for those two figures, which is worth being
        honest about -- the per-row chain still has to hold, and that is where
        the real proof lives.
        """
        def balance_of(row):
            return as_paise(mapping.get(row, "balance"))

        opening = closing = None
        for row in summaries.get("opening", []) + markers[:1]:
            opening = balance_of(row) if balance_of(row) is not None else opening
        for row in summaries.get("closing", []) + markers[-1:]:
            closing = balance_of(row) if balance_of(row) is not None else closing

        first, last = transactions[0], transactions[-1]
        if opening is None:
            opening = first.balance_paise - (-first.signed_paise if liability else first.signed_paise)
        if closing is None:
            closing = last.balance_paise
        return opening, closing

    # -- header metadata ----------------------------------------------------

    @staticmethod
    def _account_number(text: str) -> str:
        match = ACCOUNT_NUMBER.search(text)
        if not match:
            return ""
        return re.sub(r"[^0-9]", "", match.group(1))

    @staticmethod
    def _ifsc(text: str) -> str:
        match = IFSC.search(text)
        return match.group(1).upper() if match else ""

    @classmethod
    def _period_start(cls, text: str, transactions):
        printed = cls._printed_period(text)
        return printed[0] if printed else min(t.date for t in transactions)

    @classmethod
    def _period_end(cls, text: str, transactions):
        printed = cls._printed_period(text)
        return printed[1] if printed else max(t.date for t in transactions)

    @staticmethod
    def _printed_period(text: str):
        match = PERIOD.search(text)
        if not match:
            return None
        start, end = as_date(match.group(1)), as_date(match.group(2))
        return (start, end) if start and end and start <= end else None
