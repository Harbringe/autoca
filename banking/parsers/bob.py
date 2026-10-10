"""Bank of Baroda account statement in the layout with ``Dr``/``Cr`` on the balance and one amount per row.

Format notes, from a real 10-page Cash Credit statement covering FY2025-26:

* The page has no ruled table to extract. Every row is text: ``TRAN DATE  VALUE DATE  NARRATION  [CHQ.NO.]  amount
  balance``, and the narration wraps onto the next lines, taking the amount with it when it is long. So a row is the line that
  starts with two dates plus every line after it up to the next such line, and the amount is the one money figure in it that
  is not followed by ``Dr`` or ``Cr``.
* **Only one amount is printed, never two columns**, so withdrawal against deposit cannot be read from where the amount sits.
  It is read from the running balance: what the balance did from the row before is what the row did, and the printed amount
  must equal that move to the paisa. A row that disagrees means a row was lost or read wrong, and the statement is refused.
* The balance is written ``17,92,397.34Dr``: on a Cash Credit or overdraft account that is what the client owes. It is stored
  as the bank balance (negative when owed), so a withdrawal lowers it and a deposit raises it, as on any other account.
* **Newest entry first.** The rows are put in date order before the balances are chained.
* No opening balance is printed. It is worked out from the oldest row, whose direction the balance alone cannot give (there is
  nothing before it): it is taken from the wording of that row (``BY CASH`` is a deposit, a charge is a withdrawal), and when
  the wording does not say, the statement is refused with a message that says so, rather than guessing.
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

_DATES = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s*(.*)$")
_MONEY = r"\d[\d,]*\.\d{2}"
_BALANCE = re.compile(rf"({_MONEY})\s*(Dr|Cr)\b")
_AMOUNT_ONLY = re.compile(rf"^{_MONEY}$")
_HEADER = re.compile(r"TRAN\s+DATE\s+VALUE\s+DATE\s+NARRATION", re.IGNORECASE)
_IFSC = re.compile(r"IFSC\s+Code\s*:\s*(BARB0[A-Z0-9]{6})", re.IGNORECASE)
_PERIOD = re.compile(r"Statement\s+Period\s+from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_ACCOUNT = re.compile(r"Account\s+No\s*:\s*([0-9Xx*]{6,24})", re.IGNORECASE)
_HOLDER = re.compile(r"Account\s+Holder\s+Name\s*:\s*([^\n]+?)\s+Address\s*:", re.IGNORECASE)
#: Lines at the foot of every page.
_FOOTER = re.compile(r"Contact-Us@|computer-generated statement|^Page\s+\d+\s+of\s+\d+", re.IGNORECASE)

#: How the oldest row's wording says which way it went. Used for that one row only.
_CREDIT_WORDS = re.compile(r"^(BY\s+(CASH|CLG|CLEARING|TRANSFER|CHEQUE)|CASH\s+DEPOSIT|DEPOSIT|INT\.?\s*PD|INTEREST\s+(PAID|CREDIT)|REFUND)", re.IGNORECASE)
_DEBIT_WORDS = re.compile(r"(CHARGES?|CHGS?|PENAL|INT\.?\s*COLL|SMS|ATM|ISSUE|WITHDRAWAL|WDL|FOLIO|FEE|GST)\b", re.IGNORECASE)


class BankOfBarodaParser(StatementParser):
    bank_code = "BOB"
    version = 1

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        first = document.pages[0].text if document.pages else ""
        return bool(_IFSC.search(first) and _HEADER.search(first) and "BALANCE" in first.upper())

    def parse(self, document: PdfDocument) -> ParsedStatement:
        head = document.pages[0].text
        period = _PERIOD.search(head)
        account = _ACCOUNT.search(head)
        if not period or not account:
            raise StatementParseError("The account number or the statement period could not be found on the first page.")
        ifsc = _IFSC.search(head)
        holder = _HOLDER.search(head)

        rows = self._rows(document)
        if not rows:
            raise StatementParseError("No transactions were found in this statement.")
        # Newest first as printed; the balances only chain in date order.
        if rows[0]["date"] >= rows[-1]["date"]:
            rows.reverse()

        # The oldest row's direction is not in the balance chain (nothing precedes it).
        first = rows[0]
        words = first["narration"]
        if _CREDIT_WORDS.search(words):
            first_effect = first["amount"]
        elif _DEBIT_WORDS.search(words):
            first_effect = -first["amount"]
        else:
            raise StatementParseError(
                f"This statement does not print its opening balance, and the oldest row ({first['date']:%d-%m-%Y}, "
                f"{words[:40]!r}) does not say whether it was a withdrawal or a deposit. Upload a statement that includes "
                "the opening balance, or the one for the period before it."
            )
        opening = first["balance"] - first_effect

        transactions: list[ParsedTransaction] = []
        previous = opening
        for number, row in enumerate(rows, start=1):
            delta = row["balance"] - previous
            if abs(delta) != row["amount"]:
                raise StatementParseError(
                    f"Row {number} ({row['date']:%d-%m-%Y}, {row['narration'][:50]!r}) prints an amount of "
                    f"{row['amount'] / 100:,.2f} but the balance moved by {abs(delta) / 100:,.2f}. A row is missing or was "
                    "read into the wrong place; nothing was imported."
                )
            transactions.append(
                ParsedTransaction(
                    row_number=number,
                    date=row["date"],
                    narration=row["narration"],
                    debit_paise=row["amount"] if delta < 0 else 0,
                    credit_paise=row["amount"] if delta > 0 else 0,
                    balance_paise=row["balance"],
                    cheque_number=row["cheque"],
                )
            )
            previous = row["balance"]

        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=account.group(1).upper(),
            account_holder=collapse_whitespace(holder.group(1)) if holder else "",
            ifsc=ifsc.group(1).upper() if ifsc else "",
            period_start=parse_date(period.group(1)),
            period_end=parse_date(period.group(2)),
            opening_balance_paise=opening,
            closing_balance_paise=transactions[-1].balance_paise,
            transactions=tuple(transactions),
        )

    # -- rows ---------------------------------------------------------------

    def _rows(self, document: PdfDocument) -> list[dict]:
        blocks: list[list[str]] = []
        for page in document.pages:
            for raw in (page.text or "").splitlines():
                line = raw.strip()
                if not line or _FOOTER.search(line) or _HEADER.search(line):
                    continue
                if _DATES.match(line):
                    blocks.append([line])
                elif blocks:
                    blocks[-1].append(line)
        return [self._row(block) for block in blocks]

    @staticmethod
    def _row(block: list[str]) -> dict:
        match = _DATES.match(block[0])
        date = parse_date(match.group(1))
        text = " ".join([match.group(3), *block[1:]])
        balances = _BALANCE.findall(text)
        if len(balances) != 1:
            raise StatementParseError(f"The row dated {match.group(1)} does not carry exactly one balance ({text[:60]!r}).")
        figure, side = balances[0]
        owed = parse_amount(figure)
        balance = -owed if side.lower() == "dr" else owed  # Dr on a cash credit account is what the client owes
        without_balance = _BALANCE.sub(" ", text)
        amounts = re.findall(_MONEY, without_balance)
        if len(amounts) != 1:
            raise StatementParseError(
                f"The row dated {match.group(1)} has {len(amounts)} amounts where one is expected ({text[:70]!r})."
            )
        amount = parse_amount(amounts[0])
        before_amount = without_balance.split(amounts[0], 1)[0].split()
        cheque = ""
        if before_amount and before_amount[-1].isdigit() and 1 <= len(before_amount[-1]) <= 9 and len(before_amount) > 1:
            cheque = before_amount[-1]
        narration_words = [w for w in without_balance.split() if not _AMOUNT_ONLY.match(w)]
        if cheque and narration_words and narration_words[-1] == cheque:
            narration_words.pop()
        elif cheque:
            narration_words = [w for w in narration_words if w != cheque] if narration_words.count(cheque) == 1 else narration_words
        return {
            "date": date,
            "amount": amount,
            "balance": balance,
            "cheque": cheque,
            "narration": collapse_whitespace(" ".join(narration_words)),
        }
