"""Reading a GST invoice from its text layer, and proving what was read.

A reading is a *draft*: what the file appears to say, plus the checks that say how far to trust it. A person confirms every
one before anything is booked. Nothing here calls a model, so nothing leaves the server; a scan (no text layer) is refused
rather than guessed at.

The proof is arithmetic that a correct invoice must satisfy whatever its layout:

* taxable value + CGST + SGST + IGST + cess + round-off equals the invoice total, to the paise;
* tax is either IGST or CGST with an equal SGST, never both;
* every GSTIN used passes its check character;
* the invoice has a number and a plausible date.

Where a page prints a tax line more than once (a HSN summary under the totals) the candidate readings are tried and the one
that proves is kept, so a layout quirk cannot make a good invoice look wrong or a wrong reading look right: if nothing
proves, the first reading is returned with the failing check named and a person fixes it.
"""

from __future__ import annotations

import datetime
import itertools
import re
from dataclasses import dataclass, field

from core.identifiers import is_valid_gstin
from core.money import MoneyError, to_paise

EARLIEST_INVOICE_DATE = datetime.date(2017, 7, 1)  # GST began


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Reading:
    supplier_name: str = ""
    gstins: list[str] = field(default_factory=list)
    invoice_no: str = ""
    invoice_date: datetime.date | None = None
    taxable_paise: int | None = None
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    round_off_paise: int = 0
    total_paise: int | None = None
    checks: list[Check] = field(default_factory=list)

    @property
    def proved(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_NUMBER = re.compile(r"(?<![\w.])\(?-?\s?\d[\d,]*(?:\.\d{1,2})?\)?(?![\w])")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_NUM = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")
_DATE_TXT = re.compile(r"\b(\d{1,2})[-\s/]([A-Za-z]{3})[a-z]*[-\s/,.]*(\d{2,4})\b")
_INVOICE_NO = re.compile(
    r"(?:tax\s+invoice|invoice|inv|bill)\s*(?:no|number|num|#)\b\.?\s*[:\-#]?\s*([A-Za-z0-9][A-Za-z0-9/\-_.]{0,31})", re.I
)
_DATE_LABEL = re.compile(r"(?:invoice\s+date|date\s+of\s+invoice|inv\.?\s+date|bill\s+date|dated|date)\b[^0-9A-Za-z]{0,6}(.{0,24})", re.I)

_LABELS = {
    "taxable": re.compile(r"taxable\s+(?:value|amount|amt)|total\s+before\s+tax|assessable\s+value|sub\s*-?\s*total|net\s+amount", re.I),
    "cgst": re.compile(r"\bcgst\b", re.I),
    "sgst": re.compile(r"\b(?:sgst|utgst)\b", re.I),
    "igst": re.compile(r"\bigst\b", re.I),
    "cess": re.compile(r"\bcess\b", re.I),
    "round_off": re.compile(r"round(?:ing)?\s*-?\s*off|rounded\s+off", re.I),
    "total": re.compile(
        r"grand\s+total|total\s+invoice\s+value|invoice\s+(?:value|total|amount)|total\s+amount|amount\s+payable|net\s+payable|\btotal\b", re.I
    ),
}
_NOT_A_NAME = re.compile(r"invoice|original|duplicate|triplicate|gstin|page|\bcopy\b|e-?way|irn|ack\b|bill\s+of\s+supply|^[\d\W]+$", re.I)


def read_invoice(text: str, *, today: datetime.date | None = None) -> Reading:
    """Read ``text`` (the invoice's text layer) into a draft and the checks that prove or fault it."""
    today = today or datetime.date.today()
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    reading = Reading()
    reading.supplier_name = _supplier_name(lines)
    reading.gstins = _gstins(text)
    reading.invoice_no = _invoice_no(text)
    reading.invoice_date = _invoice_date(lines)

    candidates = {name: _amounts_on(lines, pattern, name) for name, pattern in _LABELS.items()}
    _choose_amounts(reading, candidates)
    reading.checks = _checks(reading, today)
    return reading


def _supplier_name(lines: list[str]) -> str:
    for line in lines[:8]:
        if not _NOT_A_NAME.search(line) and len(line) >= 3:
            return line[:120]
    return ""


def _gstins(text: str) -> list[str]:
    found: list[str] = []
    for candidate in _GSTIN.findall(text.upper()):
        if is_valid_gstin(candidate) and candidate not in found:
            found.append(candidate)
    return found


def _invoice_no(text: str) -> str:
    match = _INVOICE_NO.search(text)
    if not match:
        return ""
    value = match.group(1).strip(".-/_")
    # "Invoice Date" can follow the label on the same line: that is not a number.
    return "" if value.lower() in {"date", "dt", "no", "number"} else value[:64]


def _invoice_date(lines: list[str]) -> datetime.date | None:
    for line in lines:
        match = _DATE_LABEL.search(line)
        if match:
            parsed = _parse_date(match.group(1))
            if parsed:
                return parsed
    for line in lines:
        parsed = _parse_date(line)
        if parsed:
            return parsed
    return None


def _parse_date(text: str) -> datetime.date | None:
    for match in _DATE_NUM.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        year = year + 2000 if year < 100 else year
        try:
            return datetime.date(year, month, day)
        except ValueError:
            continue
    for match in _DATE_TXT.finditer(text):
        month = _MONTHS.get(match.group(2).lower())
        if month is None:
            continue
        year = int(match.group(3))
        year = year + 2000 if year < 100 else year
        try:
            return datetime.date(year, month, int(match.group(1)))
        except ValueError:
            continue
    return None


def _paise(token: str) -> int | None:
    cleaned = token.strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")") or cleaned.lstrip("(").startswith("-")
    digits = cleaned.strip("()").replace("-", "").replace(",", "").replace(" ", "")
    if not digits:
        return None
    try:
        value = to_paise(digits)
    except MoneyError:
        return None
    return -value if negative else value


def _amounts_on(lines: list[str], label: re.Pattern, name: str) -> list[int]:
    """The last amount on each line that names ``label``, in page order.

    A rate (``@ 9%``) and a count are not amounts: tokens followed by ``%`` are dropped, and a figure with no decimals is
    only taken when nothing with decimals shares its line.
    """
    found: list[int] = []
    for line in lines:
        if not label.search(line):
            continue
        # The "total" label also appears inside "total before tax" and "taxable"; those are other lines.
        if name == "total" and _LABELS["taxable"].search(line):
            continue
        cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", " ", line)
        tokens = _NUMBER.findall(cleaned)
        with_decimals = [t for t in tokens if "." in t]
        picked = with_decimals or tokens
        if not picked:
            continue
        amount = _paise(picked[-1])
        if amount is not None:
            found.append(amount)
    return found


def _options(values: list[int]) -> list[int]:
    """The readings to try for one line of the invoice: the last printed, the first, their sum, or nothing."""
    if not values:
        return [0]
    out: list[int] = []
    for candidate in (values[-1], values[0], sum(values)):
        if candidate not in out:
            out.append(candidate)
    return out


def _choose_amounts(reading: Reading, candidates: dict[str, list[int]]) -> None:
    taxable_options = _options(candidates["taxable"]) if candidates["taxable"] else [None]
    total_options = [candidates["total"][-1], max(candidates["total"])] if candidates["total"] else [None]
    heads = ["cgst", "sgst", "igst", "cess", "round_off"]
    first: tuple | None = None
    for taxable, total, *rest in itertools.product(
        taxable_options, dict.fromkeys(total_options), *(_options(candidates[h]) for h in heads)
    ):
        values = dict(zip(heads, rest, strict=True))
        if first is None:
            first = (taxable, total, values)
        if taxable is not None and total is not None and _ties(taxable, total, values) and _split_ok(values):
            _assign(reading, taxable, total, values)
            return
    if first is not None:
        _assign(reading, *first)


def _ties(taxable: int, total: int, values: dict[str, int]) -> bool:
    return taxable + values["cgst"] + values["sgst"] + values["igst"] + values["cess"] + values["round_off"] == total


def _split_ok(values: dict[str, int]) -> bool:
    return not (values["igst"] and (values["cgst"] or values["sgst"])) and values["cgst"] == values["sgst"]


def _assign(reading: Reading, taxable, total, values) -> None:
    reading.taxable_paise = taxable
    reading.total_paise = total
    reading.cgst_paise = values["cgst"]
    reading.sgst_paise = values["sgst"]
    reading.igst_paise = values["igst"]
    reading.cess_paise = values["cess"]
    reading.round_off_paise = values["round_off"]


def _checks(reading: Reading, today: datetime.date) -> list[Check]:
    checks: list[Check] = []
    has_amounts = reading.taxable_paise is not None and reading.total_paise is not None
    checks.append(Check("amounts_found", has_amounts, "" if has_amounts else "The taxable value or the total could not be found."))
    if has_amounts:
        values = {
            "cgst": reading.cgst_paise, "sgst": reading.sgst_paise, "igst": reading.igst_paise,
            "cess": reading.cess_paise, "round_off": reading.round_off_paise,
        }
        tied = _ties(reading.taxable_paise, reading.total_paise, values)
        checks.append(Check("arithmetic", tied, "" if tied else "Taxable value plus tax and round-off does not equal the total."))
        split = _split_ok(values)
        checks.append(Check("tax_split", split, "" if split else "Tax is either IGST or an equal CGST and SGST, not both."))
    checks.append(Check("gstin", bool(reading.gstins), "" if reading.gstins else "No valid GSTIN was found on the invoice."))
    checks.append(Check("invoice_no", bool(reading.invoice_no), "" if reading.invoice_no else "The invoice number could not be found."))
    date_ok = reading.invoice_date is not None and EARLIEST_INVOICE_DATE <= reading.invoice_date <= today + datetime.timedelta(days=1)
    checks.append(Check("invoice_date", date_ok, "" if date_ok else "The invoice date is missing or not a plausible one."))
    return checks
