"""Bank of Baroda branch ledger print ("REP31 Customer Account Ledger"), the report a branch hands over for a period.

Format notes, from a real 9-page savings account report:

* The first page is only the report's settings (account range, period); the rows start on page 2 after ``Opening Balance : 1,12,754.82Cr``.
* Every row is one line: ``GL date  value date  tran id  [instrument]  particulars  amount  balance`` with the balance ending in ``Cr`` or
  ``Dr``. The two amount columns (debit and credit) print as one figure, so which way it went is read from the running balance, which
  must move by exactly that amount; the opening balance is printed, so even the first row is proved.
* Every page after the first repeats ``B/F Balance``, and ends with ``Page Total Credit`` / ``Page Total Debit``; the last page prints
  ``Closing Balance``, ``Total Credit`` and ``Total Debit``. The closing balance and both totals are checked against the rows.
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
    parse_amount,
    parse_date,
)

_MONEY = r"\d[\d,]*\.\d{2}"
_TITLE = re.compile(r"REP31\s+Customer\s+Account\s+Ledger", re.IGNORECASE)
_ROW = re.compile(rf"^(\d{{2}}-\d{{2}}-\d{{4}})\s+(\d{{2}}-\d{{2}}-\d{{4}})\s+(\S+)\s+(.*?)\s*({_MONEY})\s+({_MONEY})\s*(Cr|Dr)$", re.IGNORECASE)
_ACCOUNT = re.compile(r"Account\s+No\s*:\s*(\d{6,24})\s+[A-Z]{3}\s+([^\n]+)", re.IGNORECASE)
_PERIOD = re.compile(r"(?:Report\s+from|Period\s*:)\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})", re.IGNORECASE)
_OPENING = re.compile(rf"Opening\s+Balance\s*:\s*({_MONEY})\s*(Cr|Dr)", re.IGNORECASE)
_CLOSING = re.compile(rf"Closing\s+Balance\s*:\s*({_MONEY})\s*(Cr|Dr)", re.IGNORECASE)
_TOTAL_CREDIT = re.compile(rf"^Total\s+Credit\s*:\s*({_MONEY})", re.IGNORECASE | re.MULTILINE)
_TOTAL_DEBIT = re.compile(rf"^Total\s+Debit\s*:\s*({_MONEY})", re.IGNORECASE | re.MULTILINE)


def _signed(figure: str, side: str) -> int:
    amount = parse_amount(figure)
    return -amount if side.lower() == "dr" else amount  # Dr: the account is overdrawn, a negative bank balance


class BankOfBarodaLedgerParser(StatementParser):
    bank_code = "BOB"
    version = 1

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        head = "\n".join(page.text or "" for page in document.pages[:2])
        return bool(_TITLE.search(head) and "BANK OF BARODA" in head.upper())

    def parse(self, document: PdfDocument) -> ParsedStatement:
        text = "\n".join(page.text or "" for page in document.pages)
        account = _ACCOUNT.search(text)
        period = _PERIOD.search(text)
        opening = _OPENING.search(text)
        closing = _CLOSING.search(text)
        if not (account and period and opening and closing):
            raise StatementParseError(
                "This Bank of Baroda ledger report does not show its account number, period, opening and closing balance. "
                "Print the full report (every page) from the branch and upload it again."
            )

        previous = _signed(*opening.groups())
        transactions: list[ParsedTransaction] = []
        for raw in text.splitlines():
            row = _ROW.match(raw.strip())
            if not row:
                continue
            gl_date, _value_date, tran_id, particulars, figure, balance_figure, side = row.groups()
            amount = parse_amount(figure)
            balance = _signed(balance_figure, side)
            delta = balance - previous
            if abs(delta) != amount:
                raise StatementParseError(
                    f"The row of {gl_date} ({particulars[:50]!r}) prints {amount / 100:,.2f} but the balance moved by "
                    f"{abs(delta) / 100:,.2f}. A row is missing or was read wrong; nothing was imported."
                )
            words = particulars.split()
            cheque = words[0] if words and words[0].isdigit() and len(words[0]) <= 9 and len(words) > 1 else ""
            transactions.append(
                ParsedTransaction(
                    row_number=len(transactions) + 1,
                    date=parse_date(gl_date),
                    narration=collapse_whitespace(" ".join(words[1:] if cheque else words)) or tran_id,
                    debit_paise=amount if delta < 0 else 0,
                    credit_paise=amount if delta > 0 else 0,
                    balance_paise=balance,
                    cheque_number=cheque,
                )
            )
            previous = balance
        if not transactions:
            raise StatementParseError("No transactions were found in this ledger report.")
        if previous != _signed(*closing.groups()):
            raise StatementParseError(
                f"The rows end at {previous / 100:,.2f}, but the report's closing balance is {closing.group(1)} {closing.group(2)}. "
                "A page is missing; upload the full report."
            )
        total_credit = _TOTAL_CREDIT.search(text)
        total_debit = _TOTAL_DEBIT.search(text)
        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=account.group(1),
            account_holder=collapse_whitespace(account.group(2)),
            period_start=parse_date(period.group(1)),
            period_end=parse_date(period.group(2)),
            opening_balance_paise=_signed(*opening.groups()),
            closing_balance_paise=previous,
            transactions=tuple(transactions),
            stated_total_debit_paise=parse_amount(total_debit.group(1)) if total_debit else None,
            stated_total_credit_paise=parse_amount(total_credit.group(1)) if total_credit else None,
        )
