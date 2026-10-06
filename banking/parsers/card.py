"""A credit-card statement: what was spent, what was paid, and what is now owed.

A card statement rarely prints a running balance, so the proof the bank-statement parsers use (every row follows from the one
before) has nothing to check. This one proves it a different way. The statement prints what was owed at the start ("previous
balance") and what is owed at the end ("total amount due"); the rows are read, a running balance is built from the start, and
the build must land exactly on the printed total due. A missing row, a doubled row or a purchase read as a payment moves
the total, so it fails the same gate (``ParsedStatement``) every other statement passes, and nothing is imported.

The card is a liability: a purchase or a charge (the statement's debit) raises what is owed, a payment or a refund (its
credit) lowers it. The account number is the masked card number the statement prints.
"""

from __future__ import annotations

import datetime
import re

from integrations.pdf.base import PdfDocument

from .base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    collapse_whitespace,
)
from .columns import as_date, as_direction, as_paise, normalise_header

#: A card's number as statements print it: groups of four with X, * or a bullet over all but the last four digits.
CARD_NUMBER = re.compile(r"(?:card\s*(?:no|number|#)?\.?|a/c)[^0-9Xx*•]{0,12}((?:[0-9Xx*•]{4}[\s-]?){3}[0-9]{4})", re.IGNORECASE)

PREVIOUS = re.compile(r"(?:previous|opening|last)\s+(?:statement\s+)?(?:balance|dues?|outstanding)", re.IGNORECASE)
TOTAL_DUE = re.compile(
    r"total\s+(?:amount\s+)?(?:payment\s+)?(?:due|dues|outstanding)|closing\s+balance|new\s+balance|"
    r"amount\s+due|total\s+amount\s+payable",
    re.IGNORECASE,
)
PERIOD = re.compile(r"(?:statement|billing)?\s*period[^0-9]{0,12}(\d{1,2}[-/ ][A-Za-z0-9]{2,9}[-/ ,]*\d{2,4})\s*(?:to|-|–)\s*(\d{1,2}[-/ ][A-Za-z0-9]{2,9}[-/ ,]*\d{2,4})", re.IGNORECASE)
STATEMENT_DATE = re.compile(r"statement\s+date[^0-9A-Za-z]{0,6}(\d{1,2}[-/ ][A-Za-z0-9]{2,9}[-/ ,]*\d{2,4})", re.IGNORECASE)

BANKS = (
    ("HDFC", r"hdfc"),
    ("ICICI", r"icici"),
    ("SBI", r"sbi\s+card|state\s+bank"),
    ("AXIS", r"axis\s+bank"),
    ("KOTAK", r"kotak"),
    ("AMEX", r"american\s+express"),
    ("CITI", r"citi"),
    ("YESBANK", r"yes\s+bank"),
    ("IDFC", r"idfc"),
    ("INDUSIND", r"indusind"),
    ("RBL", r"\brbl\b"),
    ("AU", r"au\s+small|au\s+bank"),
    ("PNB", r"punjab\s+national"),
    ("BOB", r"bank\s+of\s+baroda"),
)

MONEY_TOKEN = re.compile(r"-?\(?\d[\d,]*\.\d{2}\)?\s*(?:cr|dr)?\.?", re.IGNORECASE)


def _owed(token: str) -> int | None:
    """An amount as what is owed: ``Cr`` means the card is in credit, so it is negative; a minus sign too."""
    token = (token or "").strip()
    if not token:
        return None
    credit = bool(re.search(r"cr\.?$", token, re.IGNORECASE)) or token.startswith("-") or (token.startswith("(") and token.endswith(")"))
    cleaned = re.sub(r"(?i)\s*(cr|dr)\.?$", "", token).strip("()- ")
    value = as_paise(cleaned)
    if value is None:
        return None
    return -abs(value) if credit else abs(value)


class CardStatementParser(StatementParser):
    """Reads a credit-card statement, or refuses clearly."""

    bank_code = "CARD"
    version = 1

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        # Chosen by the document's title in ``banking.parsers.detect_parser``, never by trying and falling back.
        return False

    def parse(self, document: PdfDocument) -> ParsedStatement:
        text = document.text
        number = self._card_number(text)
        previous, total_due = self._summary(document)
        rows = self._rows(document)
        if not rows:
            raise StatementParseError("No transactions were found in this card statement. A scan has no table to read.")

        balance = previous
        transactions = []
        for number_, (date, narration, debit, credit) in enumerate(rows, start=1):
            balance += debit - credit
            transactions.append(
                ParsedTransaction(
                    row_number=number_, date=date, narration=narration[:500], cheque_number="", branch_code="",
                    debit_paise=debit, credit_paise=credit, balance_paise=balance,
                )
            )
        start, end = self._period(text, [t.date for t in transactions])
        return ParsedStatement(
            bank_code=self._bank(text),
            account_number=number,
            account_holder="",
            ifsc="",
            period_start=start,
            period_end=end,
            opening_balance_paise=previous,
            closing_balance_paise=total_due,
            transactions=tuple(transactions),
            kind="CARD",
            liability=True,
        )

    # -- header ---------------------------------------------------------------

    @staticmethod
    def _card_number(text: str) -> str:
        match = CARD_NUMBER.search(text)
        if not match:
            raise StatementParseError("The card number could not be found on this statement, so it cannot be filed against a card.")
        return re.sub(r"[\s-]", "", match.group(1)).upper().replace("*", "X").replace("•", "X")

    @staticmethod
    def _bank(text: str) -> str:
        head = text[:1500].lower()
        for code, pattern in BANKS:
            if re.search(pattern, head):
                return code
        return "CARD"

    @staticmethod
    def _period(text: str, dates):
        match = PERIOD.search(text)
        if match:
            start, end = as_date(match.group(1).strip()), as_date(match.group(2).strip())
            if start and end and start <= end:
                return start, end
        stated = STATEMENT_DATE.search(text)
        end = as_date(stated.group(1)) if stated else None
        first = min(dates)
        last = max(dates)
        return min(first, end) if end else first, max(last, end) if end else last

    # -- the proof's two figures -----------------------------------------------

    @classmethod
    def _summary(cls, document: PdfDocument) -> tuple[int, int]:
        """What was owed before and what is owed now, as the statement prints them. Both are required: they are the proof."""
        found: dict[str, int] = {}
        # A summary box: the labels in one row of a table and their figures in the next.
        for table in document.tables():
            for index, row in enumerate(table[:-1]):
                below = table[index + 1]
                for column, cell in enumerate(row):
                    for key, pattern in (("previous", PREVIOUS), ("total", TOTAL_DUE)):
                        if key not in found and pattern.search(cell or "") and column < len(below):
                            value = _owed(below[column])
                            if value is not None:
                                found[key] = value
        # Or one line of text: "Previous Balance 12,000.00".
        for line in document.text.splitlines():
            for key, pattern in (("previous", PREVIOUS), ("total", TOTAL_DUE)):
                if key not in found:
                    label = pattern.search(line)
                    if label:
                        token = MONEY_TOKEN.search(line[label.end():])
                        value = _owed(token.group(0)) if token else None
                        if value is not None:
                            found[key] = value
        if "previous" not in found or "total" not in found:
            missing = "the previous balance" if "previous" not in found else "the total amount due"
            raise StatementParseError(
                f"This card statement does not print {missing} where it can be read. Both are needed: they are what the "
                f"rows are proved against. Nothing was guessed."
            )
        return found["previous"], found["total"]

    # -- rows -----------------------------------------------------------------

    @classmethod
    def _rows(cls, document: PdfDocument) -> list[tuple[datetime.date, str, int, int]]:
        rows = []
        for table in document.tables():
            # A summary box (previous balance, total due, due date) carries a date and an amount but is not a transaction.
            if any(PREVIOUS.search(c or "") or TOTAL_DUE.search(c or "") for row in table for c in row):
                continue
            columns = cls._split_columns(table)
            for cells in table:
                cells = [c or "" for c in cells]
                date = next((as_date(c) for c in cells if as_date(c)), None)
                if date is None:
                    continue
                parsed = cls._amount(cells, columns)
                if parsed is None:
                    continue
                debit, credit = parsed
                narration = max((c for c in cells if c.strip() and not as_date(c) and as_paise(c) is None), key=len, default="")
                rows.append((date, collapse_whitespace(narration), debit, credit))
        return rows

    @staticmethod
    def _split_columns(table) -> tuple[int, int] | None:
        """Separate debit and credit columns, when the table's header names both."""
        for row in table[:3]:
            debit = credit = None
            for index, cell in enumerate(row):
                key = normalise_header(cell)
                if key in {"debit", "debits", "purchase", "purchases", "charges", "dr", "withdrawal", "spends"} and debit is None:
                    debit = index
                if key in {"credit", "credits", "payment", "payments", "payments/credits", "cr", "deposit", "paymentscredits"} and credit is None:
                    credit = index
            if debit is not None and credit is not None:
                return debit, credit
        return None

    @staticmethod
    def _amount(cells, columns) -> tuple[int, int] | None:
        if columns:
            debit_cell = cells[columns[0]] if columns[0] < len(cells) else ""
            credit_cell = cells[columns[1]] if columns[1] < len(cells) else ""
            debit, credit = as_paise(debit_cell), as_paise(credit_cell)
            if debit and not credit:
                return abs(debit), 0
            if credit and not debit:
                return 0, abs(credit)
            return None
        money = [c for c in cells if re.search(r"\.\d{2}", c) and _owed(c) is not None]
        if not money:
            return None
        token = money[-1]
        value = _owed(token)
        if value is None or value == 0:
            return None
        marker = next((as_direction(c) for c in cells if c.strip().upper().rstrip(".") in {"DR", "CR"}), None)
        if marker == "CR":
            return 0, abs(value)
        if marker == "DR":
            return abs(value), 0
        # No marker: a "Cr" suffix or a minus sign is a credit (a payment or a refund); anything else is a debit.
        return (0, abs(value)) if value < 0 else (value, 0)
