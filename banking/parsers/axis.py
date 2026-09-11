"""Axis Bank savings/current account statement.

Format notes, from a real 3-page statement covering FY2025-26:

* The transaction table is ruled, so cells come out of the table extractor
  already separated. Debit and Credit are genuinely distinct columns and are
  never inferred.
* The table continues onto later pages **without repeating its header**, so the
  column mapping is learned once and carried forward. A parser that expected a
  header per page would silently drop every page after the first.
* Long narration wraps inside its cell and arrives with embedded newlines; the
  wrap position is a rendering artefact and is collapsed away.
* Three rows in the table are not transactions: ``OPENING BALANCE``,
  ``TRANSACTION TOTAL`` and ``CLOSING BALANCE``. They are the statement's own
  arithmetic, and are fed straight into the check in
  :class:`~banking.parsers.base.ParsedStatement` rather than discarded.
* The last page is legends and regulatory boilerplate with no table at all.
"""

from __future__ import annotations

import re

from integrations.pdf.base import PdfDocument

from .base import (
    ZERO,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    collapse_whitespace,
    parse_amount,
    parse_date,
)

ACCOUNT_AND_PERIOD = re.compile(
    r"Statement\s+of\s+Axis\s+Account\s+No[:\s]+(?P<account>\d+)\s+"
    r"for\s+the\s+period\s*\(\s*From[:\s]+(?P<start>[\d\-/]+)\s+"
    r"To[:\s]+(?P<end>[\d\-/]+)\s*\)",
    re.IGNORECASE,
)
IFSC = re.compile(r"IFSC\s+Code[:\s]+([A-Z]{4}0[A-Z0-9]{6})", re.IGNORECASE)

#: Header cell text (lowercased, non-alphanumerics stripped) -> canonical field.
COLUMN_ALIASES = {
    "trandate": "date",
    "transactiondate": "date",
    "date": "date",
    "chqno": "cheque_number",
    "chequeno": "cheque_number",
    "particulars": "narration",
    "description": "narration",
    "debit": "debit",
    "withdrawal": "debit",
    "withdrawalamt": "debit",
    "credit": "credit",
    "deposit": "credit",
    "depositamt": "credit",
    "balance": "balance",
    "closingbalance": "balance",
    "initbr": "branch_code",
    "branch": "branch_code",
}
REQUIRED_COLUMNS = ("date", "narration", "debit", "credit", "balance")

OPENING_LABEL = "OPENING BALANCE"
CLOSING_LABEL = "CLOSING BALANCE"
TOTALS_LABEL = "TRANSACTION TOTAL"


def _normalise_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (cell or "").lower())


class AxisStatementParser(StatementParser):
    bank_code = "AXIS"

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        text = document.text
        return bool(ACCOUNT_AND_PERIOD.search(text)) or "AXIS BANK LTD" in text.upper()

    def parse(self, document: PdfDocument) -> ParsedStatement:
        text = document.text
        meta = ACCOUNT_AND_PERIOD.search(text)
        if not meta:
            raise StatementParseError(
                "Could not find the Axis account/period header line. Either this "
                "is not an Axis statement or the document has no text layer."
            )

        period_start = parse_date(meta["start"])
        period_end = parse_date(meta["end"])
        if not period_start or not period_end:
            raise StatementParseError(
                f"Unreadable statement period: {meta['start']!r} to {meta['end']!r}."
            )

        columns: dict[str, int] = {}
        transactions: list[ParsedTransaction] = []
        opening = closing = total_debit = total_credit = None

        for table in document.tables():
            for row in table:
                if not any(cell.strip() for cell in row):
                    continue

                header = self._read_header(row)
                if header:
                    columns = header
                    continue
                if not columns:
                    raise StatementParseError(
                        "Found table rows before any recognisable column header. "
                        "The extractor returned the table in an unexpected order."
                    )

                cell = _Row(row, columns)
                label = collapse_whitespace(cell.get("narration")).upper()

                if label.startswith(OPENING_LABEL):
                    opening = parse_amount(cell.get("balance"))
                    continue
                if label.startswith(CLOSING_LABEL):
                    closing = parse_amount(cell.get("balance"))
                    continue
                if label.startswith(TOTALS_LABEL):
                    total_debit = parse_amount(cell.get("debit"))
                    total_credit = parse_amount(cell.get("credit"))
                    continue

                transactions.append(self._read_transaction(cell, len(transactions) + 1))

        if opening is None:
            raise StatementParseError(f"No {OPENING_LABEL} row found in the statement table.")
        if closing is None:
            raise StatementParseError(f"No {CLOSING_LABEL} row found in the statement table.")

        ifsc = IFSC.search(text)
        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=meta["account"],
            account_holder=self._account_holder(document),
            ifsc=ifsc.group(1).upper() if ifsc else "",
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening,
            closing_balance=closing,
            stated_total_debit=total_debit,
            stated_total_credit=total_credit,
            transactions=tuple(transactions),
        )

    # -- row handling -------------------------------------------------------

    @staticmethod
    def _read_header(row) -> dict[str, int] | None:
        """Return a column map if ``row`` is the table header, else None."""
        mapping = {
            COLUMN_ALIASES[key]: index
            for index, cell in enumerate(row)
            if (key := _normalise_header(cell)) in COLUMN_ALIASES
        }
        if all(field in mapping for field in REQUIRED_COLUMNS):
            return mapping
        return None

    @staticmethod
    def _read_transaction(cell: _Row, row_number: int) -> ParsedTransaction:
        date = parse_date(cell.get("date"))
        if date is None:
            raise StatementParseError(
                f"Table row {row_number} carries an amount but no readable date "
                f"({cell.get('date')!r}, {collapse_whitespace(cell.get('narration'))[:60]!r}). "
                f"Refusing to skip it: a dropped row breaks the balance chain "
                f"further down and is harder to diagnose there."
            )
        return ParsedTransaction(
            row_number=row_number,
            date=date,
            narration=collapse_whitespace(cell.get("narration")),
            cheque_number=collapse_whitespace(cell.get("cheque_number")),
            debit=parse_amount(cell.get("debit")) or ZERO,
            credit=parse_amount(cell.get("credit")) or ZERO,
            balance=parse_amount(cell.get("balance")) or ZERO,
            branch_code=collapse_whitespace(cell.get("branch_code")),
        )

    @staticmethod
    def _account_holder(document: PdfDocument) -> str:
        for line in document.pages[0].text.splitlines():
            if line.strip():
                return collapse_whitespace(line)
        return ""


class _Row:
    """A table row addressed by canonical column name instead of by index."""

    __slots__ = ("_row", "_columns")

    def __init__(self, row, columns: dict[str, int]):
        self._row = row
        self._columns = columns

    def get(self, field: str) -> str:
        index = self._columns.get(field)
        if index is None or index >= len(self._row):
            return ""
        return self._row[index]
