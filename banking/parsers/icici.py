"""ICICI Bank savings or current account statement, the e-statement layout with numbered rows.

Format notes, from a real FY2025-26 statement:

* **No ruled rows.** The table extractor finds only the header, so the rows are read from where each word sits on the page:
  ``S No.  Transaction Date  Cheque Number  Transaction Remarks  Withdrawal  Deposit  Balance``.
* **One amount per row, in one of two columns.** Which column it is under says whether it is a withdrawal or a deposit
  (the amount's position against the two headers). That reading is then checked against the running balance on every row, so a
  mis-placed amount cannot get through.
* **The remarks wrap above and below the row's own line.** A row's remark lines start 5 points above its amount line and follow
  every 10 points, so they are given to the row by position, not guessed from order. Lines at the top of a page, above the first
  row's own remark lines, are the tail of the last row of the page before.
* **The printed period is not the rows' period.** The title says, for example, "March 26, 2026 - March 30, 2026" over rows dated
  April 2025 onward. The period used is the first to the last row dated, unless the printed one really does hold them all.
* **No opening or closing balance is printed.** The opening is worked out from the first row (its balance less its effect) and
  every later row must follow from the one before it, so a row lost or doubled anywhere in the middle breaks the proof. A row
  lost at the very end cannot be seen here; the statement that follows is checked against this one's closing balance.
* Dates are ``dd.mm.yyyy``.
"""

from __future__ import annotations

import re

from integrations.pdf.base import PdfDocument, PdfLine

from .base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
    StatementParser,
    collapse_whitespace,
    parse_amount,
    parse_date,
)

_TITLE = re.compile(r"Statement\s+of\s+Transactions\s+in\s+(?:Saving|Savings|Current)\s+Account\s+no\.?\s*([0-9Xx*]+)", re.IGNORECASE)
_PERIOD = re.compile(r"for\s+the\s+period\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*-\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", re.IGNORECASE)
_HOLDER = re.compile(r"^(?P<name>.+?)\s+Your\s+Base\s+Branch", re.IGNORECASE)
_DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_MONEY = re.compile(r"^\d[\d,]*\.\d{2}$")
_SNO = re.compile(r"^\d{1,5}$")

#: Where a row's first remark line sits against its amount line, and the halfway point used to tell which row a line belongs to.
HEAD_OFFSET = 5.0
SPLIT = 7.5


class IciciStatementParser(StatementParser):
    bank_code = "ICICI"
    version = 1

    @classmethod
    def detect(cls, document: PdfDocument) -> bool:
        if not document.pages or not document.pages[0].lines:
            return False
        first = document.pages[0].text
        header = any({"Withdrawal", "Deposit", "Balance"} <= {w.text for w in line.words} for line in document.pages[0].lines)
        return bool(_TITLE.search(first) and re.search(r"ICICI", first, re.IGNORECASE) and header)

    def parse(self, document: PdfDocument) -> ParsedStatement:
        first = document.pages[0]
        title = _TITLE.search(first.text)
        if not title:
            raise StatementParseError("The account number could not be found on the first page.")
        holder = next((m.group("name") for line in first.text.splitlines() if (m := _HOLDER.match(line))), "")

        rows: list[dict] = []
        for page in document.pages:
            rows.extend(self._page_rows(page, rows))
        if not rows:
            raise StatementParseError("No transactions were found in this statement.")

        rows = order_within_days(rows)
        opening = rows[0]["balance"] - rows[0]["effect"]
        transactions = [
            ParsedTransaction(
                row_number=n,
                date=row["date"],
                narration=row["narration"],
                debit_paise=row["amount"] if row["effect"] < 0 else 0,
                credit_paise=row["amount"] if row["effect"] > 0 else 0,
                balance_paise=row["balance"],
                cheque_number=row["cheque"],
            )
            for n, row in enumerate(rows, start=1)
        ]
        dates = [t.date for t in transactions]
        start, end = min(dates), max(dates)
        printed = _PERIOD.search(first.text)
        if printed:
            p_start, p_end = _printed_date(printed.group(1)), _printed_date(printed.group(2))
            if p_start and p_end and p_start <= start and end <= p_end:
                start, end = p_start, p_end

        return ParsedStatement(
            bank_code=self.bank_code,
            account_number=title.group(1).upper(),
            account_holder=collapse_whitespace(holder),
            ifsc="",
            period_start=start,
            period_end=end,
            opening_balance_paise=opening,
            closing_balance_paise=transactions[-1].balance_paise,
            transactions=tuple(transactions),
        )

    # -- a page ---------------------------------------------------------------

    def _page_rows(self, page, earlier: list[dict]) -> list[dict]:
        columns = self._columns(page.lines)
        if columns is None:
            return []  # a page with no table on it (the notes at the end)
        withdrawal, deposit, remarks_x0, money_x0 = columns
        mains = [line for line in page.lines if self._is_row_line(line)]
        if not mains:
            return []

        def in_remarks(word) -> bool:
            return remarks_x0 - 3 <= word.x0 and word.x1 <= money_x0

        out: list[dict] = []
        for index, line in enumerate(mains):
            lower = mains[index + 1].top - SPLIT if index + 1 < len(mains) else float("inf")
            upper = line.top - SPLIT
            narration_lines = [
                " ".join(w.text for w in other.words if in_remarks(w))
                for other in page.lines
                if upper <= other.top < lower and other.words and not (other is not line and self._is_row_line(other))
            ]
            numbers = [w for w in line.words if _MONEY.match(w.text) and w.x0 >= money_x0 - 5]
            if len(numbers) != 2:
                raise StatementParseError(
                    f"Row {line.words[0].text} ({line.words[1].text}) does not carry exactly an amount and a balance on its line."
                )
            amount_word, balance_word = numbers
            midpoint = (withdrawal + deposit) / 2
            amount = parse_amount(amount_word.text)
            effect = -amount if amount_word.centre < midpoint else amount
            cheque = " ".join(w.text for w in line.words if 100 <= w.x0 < remarks_x0 - 3)
            out.append(
                {
                    "date": parse_date(line.words[1].text, ("%d.%m.%Y",)),
                    "amount": amount,
                    "effect": effect,
                    "balance": parse_amount(balance_word.text),
                    "cheque": cheque.strip(),
                    "narration": collapse_whitespace(" ".join(t for t in narration_lines if t)),
                }
            )

        # The lines above this page's first row that are not its own (more than a row's head above it) are the tail of the last
        # row of the page before.
        first_top = mains[0].top - SPLIT
        tail = " ".join(
            " ".join(w.text for w in other.words if in_remarks(w))
            for other in page.lines
            if other.words and other.top < first_top and other.top > columns_header_bottom(page.lines)
        )
        if tail.strip() and earlier:
            earlier[-1]["narration"] = collapse_whitespace(f"{earlier[-1]['narration']} {tail}")
        return out

    @staticmethod
    def _is_row_line(line: PdfLine) -> bool:
        words = line.words
        return len(words) >= 3 and bool(_SNO.match(words[0].text)) and bool(_DATE.match(words[1].text)) and words[0].x0 < 60

    @staticmethod
    def _columns(lines) -> tuple[float, float, float, float] | None:
        """``(withdrawal centre, deposit centre, remarks start, where the money columns start)`` from the page's header, or None."""
        for line in lines:
            by_text = {w.text: w for w in line.words}
            if {"Withdrawal", "Deposit", "Balance"} <= by_text.keys():
                # The remarks column starts just right of the "Cheque Number" header; its words are left-aligned there.
                number = next(
                    (w for other in lines if abs(other.top - line.top) < 12 for w in other.words if w.text == "Number"), None
                )
                remarks_x0 = number.x1 + 4 if number else 190.0
                return by_text["Withdrawal"].centre, by_text["Deposit"].centre, remarks_x0, by_text["Withdrawal"].x0 - 8
        return None


def order_within_days(rows: list[dict]) -> list[dict]:
    """Put same-day rows in the order the running balance proves, when the bank listed them in another one.

    A bank lists the items of one day in an order that need not be the order it applied them in: a withdrawal and its reversal can
    swap places, and each keeps the balance it really had. Taken in the printed order the chain breaks, though every figure is
    right. So within one date, and only when the printed order fails, the order in which every balance follows from the one before
    it is searched for, trying at each step only the rows whose balance fits next and keeping the printed order among equals. If
    there is no such order the rows are left as printed and the statement is refused as before. Nothing is reordered across dates and
    no figure is changed.
    """
    out: list[dict] = []
    index = 0
    while index < len(rows):
        end = index
        while end + 1 < len(rows) and rows[end + 1]["date"] == rows[index]["date"]:
            end += 1
        group = rows[index : end + 1]
        previous = out[-1]["balance"] if out else None
        if previous is not None and len(group) > 1 and not _chains(previous, group):
            found = _search(previous, group)
            if found is not None:
                group = found
        out.extend(group)
        index = end + 1
    return out


#: Steps the search may take for one day before it gives up and leaves the printed order (and the refusal that follows).
SEARCH_BUDGET = 20_000


def _search(previous: int, group: list[dict]) -> list[dict] | None:
    budget = [SEARCH_BUDGET]
    chosen: list[dict] = []

    def step(running: int, remaining: list[dict]) -> bool:
        if not remaining:
            return True
        budget[0] -= 1
        if budget[0] < 0:
            return False
        for position, row in enumerate(remaining):
            if running + row["effect"] == row["balance"]:
                chosen.append(row)
                if step(row["balance"], remaining[:position] + remaining[position + 1 :]):
                    return True
                chosen.pop()
        return False

    return list(chosen) if step(previous, list(group)) else None


def _chains(previous: int, group) -> bool:
    running = previous
    for row in group:
        running += row["effect"]
        if running != row["balance"]:
            return False
    return True


def columns_header_bottom(lines) -> float:
    """The top of the lowest header line, so lines above the first row are not mistaken for the header."""
    bottom = 0.0
    for line in lines:
        if any(w.text in ("Date", "Remarks", "Withdrawal") for w in line.words):
            bottom = max(bottom, line.top)
    return bottom


def _printed_date(text: str):
    import datetime

    try:
        return datetime.datetime.strptime(" ".join(text.replace(",", " ").split()), "%B %d %Y").date()
    except ValueError:
        return None
