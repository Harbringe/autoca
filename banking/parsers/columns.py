"""Working out which column is which, and proving it with arithmetic.

Every bank lays its statement out differently. HDFC writes Withdrawal and
Deposit; SBI writes Debit and Credit; ICICI adds "(INR)" to both and puts a
serial number first; Kotak uses one Amount column with a separate Dr/Cr flag.
Header wording varies, column order varies, and some net-banking exports carry
no header row at all.

Writing a parser per bank does not scale to "any bank", and guessing the columns
is normally reckless -- a guess that puts the amount in the wrong column
produces a statement that looks perfectly reasonable and is inside out.

Which is the whole point of this module: **we do not have to guess, because the
statement can check our answer.** The balance column is a running total, so the
difference between consecutive balances is exactly what that row did to the
account. A candidate column mapping is correct if, and only if, the amounts it
picks out reproduce those differences on every row. Wrong mappings do not
almost-work; they fail on the first row and every row after it.

So the procedure is: enumerate the plausible mappings, and keep the one the
arithmetic endorses. That is a stronger check than the human column-confirmation
step the architecture sketched, and it needs nobody's attention.

The one thing arithmetic cannot check is which column holds the narration, since
it takes no part in the sums. That falls back to "the wide text column that is
not a date", and is flagged when it is unclear.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from core.money import MoneyError, to_paise

#: Header text -> the role it names. Matched after lowercasing and stripping
#: every non-alphanumeric character, so "Withdrawal Amt.", "WITHDRAWAL AMOUNT
#: (INR)" and "withdrawal_amt" all collapse to the same key.
HEADER_ALIASES = {
    # date
    "date": "date",
    "txndate": "date",
    "trandate": "date",
    "transactiondate": "date",
    "valuedate": "date",
    "valuedt": "date",
    "postdate": "date",
    "postingdate": "date",
    "bookingdate": "date",
    # narration
    "particulars": "narration",
    "narration": "narration",
    "description": "narration",
    "transactionremarks": "narration",
    "remarks": "narration",
    "details": "narration",
    "transactiondetails": "narration",
    "transactiondescription": "narration",
    # debit
    "debit": "debit",
    "debitamount": "debit",
    "debitamt": "debit",
    "withdrawal": "debit",
    "withdrawalamt": "debit",
    "withdrawalamount": "debit",
    "withdrawalamountinr": "debit",
    "withdrawals": "debit",
    "paymentsdebit": "debit",
    "dr": "debit",
    # credit
    "credit": "credit",
    "creditamount": "credit",
    "creditamt": "credit",
    "deposit": "credit",
    "depositamt": "credit",
    "depositamount": "credit",
    "depositamountinr": "credit",
    "deposits": "credit",
    "receiptscredit": "credit",
    "cr": "credit",
    # single amount column, with direction carried separately
    "amount": "amount",
    "amountinr": "amount",
    "transactionamount": "amount",
    "amountrs": "amount",
    # the Dr/Cr flag that goes with it
    "drcr": "direction",
    "crdr": "direction",
    "type": "direction",
    "transactiontype": "direction",
    "debitcredit": "direction",
    # balance
    "balance": "balance",
    "balanceinr": "balance",
    "closingbalance": "balance",
    "runningbalance": "balance",
    "balanceamt": "balance",
    "availablebalance": "balance",
    # incidental
    "chqno": "reference",
    "chequeno": "reference",
    "chqrefno": "reference",
    "chequerefno": "reference",
    "refno": "reference",
    "referenceno": "reference",
    "refnochequeno": "reference",
    "instrumentid": "reference",
    "branch": "branch",
    "initbr": "branch",
    "branchcode": "branch",
    "sno": "serial",
    "srno": "serial",
    "slno": "serial",
}

#: Cell values that mean "this row is a debit" in a direction column.
DEBIT_WORDS = {"DR", "D", "DEBIT", "W", "WITHDRAWAL"}
CREDIT_WORDS = {"CR", "C", "CREDIT", "DEP", "DEPOSIT"}

DATE_FORMATS = (
    "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
    "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %b %y",
    "%Y-%m-%d",
)

#: How many rows may fail the arithmetic before a mapping is rejected. Zero.
#: A mapping that works on nine rows in ten is not nearly right, it is wrong
#: about the tenth, and the tenth is somebody's money.
TOLERATED_FAILURES = 0


class ColumnInferenceError(RuntimeError):
    """No column mapping reproduced the statement's own running balance."""


@dataclass(frozen=True)
class ColumnMap:
    """Which column index holds which role."""

    date: int
    narration: int
    balance: int
    debit: int | None = None
    credit: int | None = None
    amount: int | None = None
    direction: int | None = None
    reference: int | None = None
    branch: int | None = None
    #: How the mapping was arrived at, for the record and for the review screen.
    source: str = "inferred"
    #: True when the narration column was picked by elimination rather than
    #: named by a header. The arithmetic cannot vouch for it.
    narration_is_a_guess: bool = False

    @property
    def has_split_amounts(self) -> bool:
        return self.debit is not None and self.credit is not None

    def get(self, row, role: str) -> str:
        index = getattr(self, role, None)
        if index is None or index >= len(row):
            return ""
        return row[index] or ""


# ---------------------------------------------------------------------------
# Cell classification
# ---------------------------------------------------------------------------


def normalise_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (cell or "").lower())


def as_date(cell: str):
    """Parse a date cell, day-first. ``None`` if it is not a date.

    Day-first throughout. Every Indian bank statement is ``dd-mm-yyyy``, and
    guessing between that and ``mm-dd-yyyy`` silently reorders a financial year
    in a way nothing downstream would notice.
    """
    import datetime

    text = re.sub(r"\s+", " ", (cell or "").strip())
    if not text:
        return None
    # A narrow date column wraps "30-Mar-" / "2026" onto two lines; the break is not part of the date.
    text = re.sub(r"([-/.]) +(?=\d)", r"\1", text)
    # Statements often append a time to the date; the date is the part we want.
    text = text.split(" ")[0] if re.match(r"^\S+\s+\d{1,2}:\d{2}", text) else text
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def as_paise(cell: str) -> int | None:
    """Parse a money cell to paise. ``None`` if it is not money or is blank."""
    text = re.sub(r"\s+", " ", (cell or "").strip())
    if not text or text in {"-", "--", "NIL", "nil"}:
        return None
    try:
        return to_paise(text)
    except MoneyError:
        return None


def as_direction(cell: str) -> str | None:
    """``"DR"``, ``"CR"``, or None, from a Dr/Cr indicator cell."""
    token = re.sub(r"[^A-Z]", "", (cell or "").upper())
    if token in DEBIT_WORDS:
        return "DR"
    if token in CREDIT_WORDS:
        return "CR"
    return None


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def infer_columns(header: list[str] | None, rows: list[list[str]]) -> ColumnMap:
    """Work out the column layout of ``rows`` and prove it against the balances.

    ``header`` is used as a hint when present and is never trusted on its own:
    a mapping read straight from the header still has to reproduce the running
    balance. Banks mislabel columns, and an export can carry the header of a
    different report entirely.
    """
    if not rows:
        raise ColumnInferenceError("No data rows to infer a layout from.")

    width = max(len(row) for row in rows)
    rows = [list(row) + [""] * (width - len(row)) for row in rows]
    profiles = [_profile(rows, index) for index in range(width)]

    named = _from_header(header, width) if header else {}
    date_index = _pick_date(named, profiles)
    money_indices = _money_columns(named, profiles)

    if date_index is None:
        raise ColumnInferenceError(
            "No column in this table reads as a date, so it is probably not a "
            "transaction table. If it is, the date format is one this parser "
            "does not know."
        )
    if len(money_indices) < 2:
        raise ColumnInferenceError(
            f"Found {len(money_indices)} numeric column(s); a statement needs at "
            f"least an amount and a running balance. The table may have been "
            f"extracted with its columns merged."
        )

    candidate = _best_mapping(rows, named, date_index, money_indices, profiles)
    if candidate is None:
        raise ColumnInferenceError(
            "No arrangement of this table's columns reproduces its own running "
            "balance. Either the balance column is not a running total, rows "
            "were lost in extraction, or the amounts and the balance disagree. "
            "Refusing to guess: a statement read into the wrong columns looks "
            "entirely plausible and is inside out."
        )
    return candidate


def _profile(rows, index) -> dict:
    """What kind of values live in this column."""
    values = [row[index] for row in rows]
    filled = [v for v in values if (v or "").strip()]
    total = max(len(values), 1)
    return {
        "index": index,
        "filled": len(filled) / total,
        "date": sum(as_date(v) is not None for v in values) / total,
        "money": sum(as_paise(v) is not None for v in values) / total,
        "direction": sum(as_direction(v) is not None for v in values) / total,
        "text_length": (sum(len(v or "") for v in filled) / len(filled)) if filled else 0,
        "always_positive_money": all(
            (as_paise(v) or 0) >= 0 for v in values if as_paise(v) is not None
        ),
        "is_row_counter": _looks_like_a_row_counter(values),
    }


def _from_header(header, width) -> dict[str, int]:
    named: dict[str, int] = {}
    for index, cell in enumerate(header[:width]):
        role = HEADER_ALIASES.get(normalise_header(cell))
        if role and role not in named:
            named[role] = index
    return named


def _pick_date(named, profiles) -> int | None:
    if "date" in named:
        return named["date"]
    dated = [p for p in profiles if p["date"] >= 0.6]
    return min(dated, key=lambda p: p["index"])["index"] if dated else None


def _money_columns(named, profiles) -> list[int]:
    """Columns that could hold money, in left-to-right order.

    A column counts if most of its filled cells parse as money. Sparse columns
    qualify too -- a debit column is empty on every credit row, which is the
    normal case and not evidence against it.
    """
    explicit = {named[role] for role in ("debit", "credit", "amount", "balance") if role in named}
    found = []
    for profile in profiles:
        if profile["index"] in explicit:
            found.append(profile["index"])
            continue
        if profile["date"] >= 0.5 or profile["is_row_counter"]:
            continue
        filled = profile["filled"]
        if filled and profile["money"] >= filled * 0.9 and profile["money"] > 0:
            found.append(profile["index"])
    return sorted(set(found))


def _looks_like_a_row_counter(values) -> bool:
    """A serial-number column parses as money and is not money.

    ``1, 2, 3, ...`` is a perfectly good rupee amount as far as the parser is
    concerned, and a column of them will happily be tried as an amount column.
    Excluding them up front keeps the search small and stops a coincidence --
    a statement whose amounts happened to tick up by one -- from ever being
    endorsed by the balance check.
    """
    numbers = []
    for value in values:
        text = (value or "").strip()
        if not text:
            continue
        if not re.fullmatch(r"\d{1,4}", text):
            return False
        numbers.append(int(text))
    if len(numbers) < 3:
        return False
    return all(later - earlier == 1 for earlier, later in zip(numbers, numbers[1:], strict=False))


def _pick_narration(named, profiles, used: set[int]) -> tuple[int, bool]:
    """The widest text column that is not doing another job."""
    if "narration" in named:
        return named["narration"], False
    candidates = [
        p for p in profiles
        if p["index"] not in used and p["date"] < 0.5 and p["money"] < 0.5 and p["filled"] > 0.3
    ]
    if not candidates:
        return -1, True
    best = max(candidates, key=lambda p: p["text_length"])
    return best["index"], True


def _best_mapping(rows, named, date_index, money_indices, profiles) -> ColumnMap | None:
    """Try every plausible layout; return the first the arithmetic endorses.

    Ordered so the likeliest and most specific arrangements are tested first:
    a balance column named in the header, then separate debit/credit columns,
    then a single amount column with a direction flag.
    """
    balance_options = (
        [named["balance"]]
        if "balance" in named
        # Otherwise the running balance is usually the rightmost money column,
        # and is the only one that is filled on every row.
        else sorted(money_indices, reverse=True)
    )

    for balance_index in balance_options:
        others = [i for i in money_indices if i != balance_index]

        for debit_index, credit_index in _amount_pairs(named, others):
            mapping = _assemble(
                named, profiles, date_index, balance_index,
                debit=debit_index, credit=credit_index,
            )
            if _reproduces_balances(rows, mapping):
                return mapping

        for amount_index in _single_amounts(named, others):
            direction_index = _direction_column(named, profiles, exclude={amount_index})
            mapping = _assemble(
                named, profiles, date_index, balance_index,
                amount=amount_index, direction=direction_index,
            )
            if _reproduces_balances(rows, mapping):
                return mapping
    return None


def _amount_pairs(named, others):
    """Candidate (debit, credit) column pairs."""
    if "debit" in named and "credit" in named:
        yield named["debit"], named["credit"]
        return
    # Both orders, because a header-less export gives no clue which is which --
    # and the arithmetic distinguishes them perfectly.
    yield from itertools.permutations(others, 2)


def _single_amounts(named, others):
    if "amount" in named:
        yield named["amount"]
        return
    yield from others


def _direction_column(named, profiles, exclude: set[int]) -> int | None:
    if "direction" in named:
        return named["direction"]
    flags = [
        p for p in profiles
        if p["index"] not in exclude and p["filled"] > 0.5 and p["direction"] >= p["filled"] * 0.9
    ]
    return flags[0]["index"] if flags else None


def _assemble(named, profiles, date_index, balance_index, **amounts) -> ColumnMap:
    used = {date_index, balance_index} | {i for i in amounts.values() if i is not None}
    narration_index, guessed = _pick_narration(named, profiles, used)
    return ColumnMap(
        date=date_index,
        narration=narration_index,
        balance=balance_index,
        reference=named.get("reference"),
        branch=named.get("branch"),
        source="header" if named else "inferred",
        narration_is_a_guess=guessed,
        **amounts,
    )


def _reproduces_balances(rows, mapping: ColumnMap) -> bool:
    """The test that makes guessing safe.

    Walks consecutive rows and checks that the change in the balance column is
    exactly what the amount columns say that row did. A wrong mapping fails on
    the first pair and keeps failing.
    """
    balances = [as_paise(mapping.get(row, "balance")) for row in rows]
    if any(balance is None for balance in balances) or len(balances) < 2:
        return False

    failures = 0
    for index in range(1, len(rows)):
        delta = balances[index] - balances[index - 1]
        signed = signed_amount(rows[index], mapping)
        if signed is None or signed != delta:
            failures += 1
            if failures > TOLERATED_FAILURES:
                return False
    return True


def signed_amount(row, mapping: ColumnMap) -> int | None:
    """What this row did to the balance: negative out, positive in.

    ``None`` when the row carries no readable amount, which for a transaction
    row means the mapping is wrong.
    """
    if mapping.has_split_amounts:
        debit = as_paise(mapping.get(row, "debit")) or 0
        credit = as_paise(mapping.get(row, "credit")) or 0
        if debit and credit:
            return None
        if not debit and not credit:
            return None
        return credit - debit

    amount = as_paise(mapping.get(row, "amount"))
    if amount is None:
        return None
    direction = as_direction(mapping.get(row, "direction")) if mapping.direction is not None else None
    if direction == "DR":
        return -abs(amount)
    if direction == "CR":
        return abs(amount)
    # No direction column: the amount's own sign is all there is. Statements
    # that write withdrawals as negatives are read correctly; those that do not
    # will fail the balance check, which is the right outcome -- an unsigned
    # amount with no indicator genuinely does not say which way it went.
    return amount
