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
    #: Who is billed; read from a scan, where the page says which is which. Blank from a text read.
    buyer_name: str = ""
    gstins: list[str] = field(default_factory=list)
    #: Who issued it and who is billed, when the page says which GSTIN is which; blank when only one is printed.
    supplier_gstin: str = ""
    buyer_gstin: str = ""
    #: Fields the reader said it could not read clearly (a scan only), for a person to check against the page.
    unsure: list[str] = field(default_factory=list)
    invoice_no: str = ""
    invoice_date: datetime.date | None = None
    taxable_paise: int | None = None
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    round_off_paise: int = 0
    total_paise: int | None = None
    #: What else a scan or photo says, for the rest of the form. Every one is optional and none is ever trusted for the books'
    #: arithmetic: they fill fields a person then confirms.
    due_date: datetime.date | None = None
    supplier_address: str = ""
    supplier_pan: str = ""
    buyer_address: str = ""
    place_of_supply: str = ""
    #: ``cash``, ``card``, ``upi``, ``bank_transfer``, ``cheque`` or ``credit``; blank when the page does not say.
    payment_mode: str = ""
    payment_terms: str = ""
    currency: str = ""
    #: A few words for what the invoice is for ("Food and beverages", "Office rent"), to suggest a ledger.
    expense_hint: str = ""
    #: The invoice's lines: description, HSN/SAC, quantity, unit, rate and amount (paise), GST rate (percent), and the line's
    #: discount and tax amounts when printed.
    items: list[dict] = field(default_factory=list)
    #: Charges outside the taxable value that make up the total: tax collected at source, freight and other charges. They
    #: join the arithmetic proof; a text read leaves them at zero.
    tcs_paise: int = 0
    other_charges_paise: int = 0
    #: The invoice's total discount, for the form; not part of the proof (the taxable value is already net of it).
    discount_paise: int | None = None
    #: Everything else a scan states that has no field of its own: document type, IRN, e-way bill, PO number, bank details, ...
    details: dict[str, str] = field(default_factory=dict)
    #: Values the model gave that failed their check and were therefore left out of the fields above, so they are not lost:
    #: ``{"field", "value", "why"}`` each. A person sees them beside the empty field.
    rejected: list[dict] = field(default_factory=list)
    #: The model's reply as it came (bounded), kept with the reading so a wrong field can be traced to what was said.
    as_read: dict = field(default_factory=dict)
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
    if len(reading.gstins) >= 2:
        # Suppliers print their own GSTIN first and the buyer's after it.
        reading.supplier_gstin, reading.buyer_gstin = reading.gstins[0], reading.gstins[1]
    reading.invoice_no = _invoice_no(text)
    reading.invoice_date = _invoice_date(lines)

    candidates = {name: _amounts_on(lines, pattern, name) for name, pattern in _LABELS.items()}
    _choose_amounts(reading, candidates)
    reading.checks = _checks(reading, today)
    return reading


def _money_value(value) -> int | None:
    """An amount a model copied, as paise; None when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        # A JSON number, as asked: through its shortest text, so 1178.58 stays 1178.58 and 0.4 stays 0.4.
        return _paise(repr(float(value)) if isinstance(value, float) else str(value))
    raw = re.sub(r"(?i)₹|\brs\.?|\binr\b", "", str(value)).strip()
    return _paise(raw) if raw else None


def reading_from_fields(fields: dict, *, today: datetime.date | None = None) -> Reading:
    """A draft from fields a vision model copied off a scan, put through the very same proof as a text read.

    Nothing the model says is trusted: every amount goes through ``to_paise`` as printed, every GSTIN through its check
    character, and the arithmetic must tie. Whatever is missing or malformed is left empty, and the checks name it.
    """
    today = today or datetime.date.today()

    def money(key: str) -> int | None:
        return _money_value(fields.get(key))

    reading = Reading(
        supplier_name=" ".join(str(fields.get("supplier_name") or "").split())[:120],
        buyer_name=" ".join(str(fields.get("buyer_name") or "").split())[:120],
    )

    rejected: list[dict] = []

    def reject(key: str, value, why: str) -> None:
        rejected.append({"field": key, "value": str(value)[:120], "why": why})

    def valid(key: str) -> str:
        candidate = re.sub(r"\s+", "", str(fields.get(key) or "")).upper()
        if candidate and not is_valid_gstin(candidate):
            reject(key, candidate, "is not a valid GSTIN (its check character fails)")
        return candidate if is_valid_gstin(candidate) else ""

    supplier, buyer = valid("supplier_gstin"), valid("buyer_gstin")
    reading.gstins = [g for g in dict.fromkeys((supplier, buyer)) if g]
    reading.supplier_gstin, reading.buyer_gstin = supplier, buyer
    reading.invoice_no = str(fields.get("invoice_no") or "").strip().strip(".-/_")[:64]
    printed_date = str(fields.get("invoice_date") or "").strip()
    try:
        reading.invoice_date = datetime.date.fromisoformat(printed_date)
    except ValueError:
        reading.invoice_date = _parse_date(printed_date)
    if printed_date and reading.invoice_date is None:
        reject("invoice_date", printed_date, "is not a date that could be understood")
    doubtful = fields.get("unsure")
    reading.unsure = [str(k) for k in doubtful if isinstance(k, str)][:12] if isinstance(doubtful, list) else []
    reading.taxable_paise = money("taxable")
    reading.total_paise = money("total")
    reading.cgst_paise = money("cgst") or 0
    reading.sgst_paise = money("sgst") or 0
    reading.igst_paise = money("igst") or 0
    reading.cess_paise = money("cess") or 0
    reading.round_off_paise = money("round_off") or 0

    def text(key: str, limit: int) -> str:
        return " ".join(str(fields.get(key) or "").split())[:limit]

    due = str(fields.get("due_date") or "").strip()
    try:
        reading.due_date = datetime.date.fromisoformat(due) if due else None
    except ValueError:
        reading.due_date = _parse_date(due)
        if reading.due_date is None:
            reject("due_date", due, "is not a date that could be understood")
    reading.supplier_address = text("supplier_address", 300)
    reading.buyer_address = text("buyer_address", 300)
    reading.place_of_supply = text("place_of_supply", 60)
    reading.payment_terms = text("payment_terms", 120)
    reading.expense_hint = text("expense_category", 80)
    pan = re.sub(r"\s+", "", str(fields.get("supplier_pan") or "")).upper()
    reading.supplier_pan = pan if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan) else ""
    if pan and not reading.supplier_pan:
        reject("supplier_pan", pan, "is not shaped like a PAN")
    mode = re.sub(r"[\s-]+", "_", str(fields.get("payment_mode") or "").strip().lower())
    reading.payment_mode = mode if mode in PAYMENT_MODES else ""
    if mode and not reading.payment_mode:
        reject("payment_mode", mode, "is not one of: " + ", ".join(PAYMENT_MODES))
    currency = str(fields.get("currency") or "").strip().upper()
    reading.currency = currency if re.fullmatch(r"[A-Z]{3}", currency) else ""
    if currency and not reading.currency:
        reject("currency", currency, "is not a three-letter currency code")
    reading.items = _items(fields.get("items"))
    reading.tcs_paise = money("tcs") or 0
    reading.other_charges_paise = (money("freight") or 0) + (money("other_charges") or 0)
    reading.discount_paise = money("discount")
    reading.details = _details(fields, reject)
    reading.rejected = rejected
    reading.as_read = _as_read(fields)
    reading.checks = _checks(reading, today)
    return reading


PAYMENT_MODES = ("cash", "card", "upi", "bank_transfer", "cheque", "credit")
DOCUMENT_TYPES = ("tax_invoice", "bill_of_supply", "credit_note", "debit_note", "receipt", "proforma", "delivery_challan", "other")

#: What a scan can state that the form has no field for, with the longest value kept for each.
_DETAIL_TEXT = {
    "irn": 70, "ack_no": 30, "eway_bill_no": 20, "vehicle_no": 20, "po_number": 60, "ship_to_name": 120, "ship_to_address": 300,
    "supplier_email": 80, "supplier_phone": 30, "bank_name": 80, "bank_account_no": 30, "amount_in_words": 200, "notes": 300,
}


def _details(fields: dict, reject) -> dict[str, str]:
    """The scan's other facts, each cleaned and bounded; a value that fails its check goes to ``reject``, not away."""
    out: dict[str, str] = {}
    for key, limit in _DETAIL_TEXT.items():
        value = " ".join(str(fields.get(key) or "").split())[:limit]
        if value:
            out[key] = value
    kind = re.sub(r"[\s-]+", "_", str(fields.get("document_type") or "").strip().lower())
    if kind:
        if kind in DOCUMENT_TYPES:
            out["document_type"] = kind
        else:
            reject("document_type", kind, "is not one of: " + ", ".join(DOCUMENT_TYPES))
    for key in ("ack_date", "po_date"):
        raw = str(fields.get(key) or "").strip()
        if raw:
            try:
                out[key] = datetime.date.fromisoformat(raw).isoformat()
            except ValueError:
                parsed = _parse_date(raw)
                if parsed:
                    out[key] = parsed.isoformat()
                else:
                    reject(key, raw, "is not a date that could be understood")
    pan = re.sub(r"\s+", "", str(fields.get("buyer_pan") or "")).upper()
    if pan:
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan):
            out["buyer_pan"] = pan
        else:
            reject("buyer_pan", pan, "is not shaped like a PAN")
    ifsc = re.sub(r"\s+", "", str(fields.get("bank_ifsc") or "")).upper()
    if ifsc:
        if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
            out["bank_ifsc"] = ifsc
        else:
            reject("bank_ifsc", ifsc, "is not shaped like an IFSC code")
    rc = fields.get("reverse_charge")
    if isinstance(rc, bool):
        out["reverse_charge"] = "yes" if rc else "no"
    elif isinstance(rc, str) and rc.strip().lower() in ("yes", "no", "y", "n", "true", "false"):
        out["reverse_charge"] = "yes" if rc.strip().lower() in ("yes", "y", "true") else "no"
    return out


_AS_READ_LIMIT = 20_000


def _bounded(value, depth: int = 0):
    """The model's reply cut down to something safe to store: strings shortened, lists and keys capped, depth limited."""
    if depth > 3:
        return None
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return value[:300]
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value[:100]]
    if isinstance(value, dict):
        return {str(k)[:60]: _bounded(v, depth + 1) for k, v in list(value.items())[:80]}
    return str(value)[:100]


def _as_read(fields: dict) -> dict:
    bounded = _bounded(fields)
    return bounded if len(repr(bounded)) <= _AS_READ_LIMIT else {"note": "reply too large to keep", "keys": sorted(map(str, fields))[:80]}


def _quantity(value):
    """A quantity as a number: a JSON number as is, or the number inside text such as "2 pcs" or "2,000"."""
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            return None
    return value


def _items(raw) -> list[dict]:
    """The lines a scan listed, cleaned: text bounded, amounts as paise, a rate only if it is a percentage."""
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw[:100]:
        if not isinstance(entry, dict):
            continue
        description = " ".join(str(entry.get("description") or "").split())[:200]
        if not description:
            continue
        quantity = _quantity(entry.get("quantity"))
        rate_pct = entry.get("gst_rate")
        sac = re.sub(r"\D", "", str(entry.get("hsn_sac") or ""))[:8]
        out.append(
            {
                "description": description,
                "hsn_sac": sac,
                "quantity": str(quantity) if isinstance(quantity, int | float) and not isinstance(quantity, bool) and 0 <= quantity < 10**9 else "",
                "unit": " ".join(str(entry.get("unit") or "").split())[:16],
                "rate_paise": _money_value(entry.get("rate")),
                "amount_paise": _money_value(entry.get("amount")),
                "gst_rate": float(rate_pct) if isinstance(rate_pct, int | float) and not isinstance(rate_pct, bool) and 0 <= rate_pct <= 100 else None,
                "discount_paise": _money_value(entry.get("discount")),
                "cgst_paise": _money_value(entry.get("cgst")),
                "sgst_paise": _money_value(entry.get("sgst")),
                "igst_paise": _money_value(entry.get("igst")),
                "total_paise": _money_value(entry.get("total")),
            }
        )
    return out



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
    """An amount as printed, in paise. Minus can be a hyphen, a Unicode minus or brackets, and may stand apart from the
    figure (``(-)0.16`` is how some invoices print a round-off); anything else around the digits is ignored."""
    cleaned = token.strip()
    negative = bool(re.search(r"[-\u2212\u2013]", cleaned)) or (cleaned.startswith("(") and cleaned.endswith(")"))
    digits = re.sub(r"[^0-9.]", "", cleaned).strip(".")
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
    return (
        taxable + values["cgst"] + values["sgst"] + values["igst"] + values["cess"] + values["round_off"]
        + values.get("tcs", 0) + values.get("other", 0) == total
    )


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
            "tcs": reading.tcs_paise, "other": reading.other_charges_paise,
        }
        tied = _ties(reading.taxable_paise, reading.total_paise, values)
        if tied:
            detail = ""
        else:
            gap = (
                reading.taxable_paise + reading.cgst_paise + reading.sgst_paise + reading.igst_paise
                + reading.cess_paise + reading.round_off_paise + reading.tcs_paise + reading.other_charges_paise
                - reading.total_paise
            )
            detail = (
                f"Taxable value plus tax and round-off is {abs(gap) / 100:,.2f} {'more' if gap > 0 else 'less'} than the total."
                + (" If the invoice rounds off, enter it as Round off." if abs(gap) < 100 else "")
            )
        checks.append(Check("arithmetic", tied, detail))
        split = _split_ok(values)
        checks.append(Check("tax_split", split, "" if split else "Tax is either IGST or an equal CGST and SGST, not both."))
    checks.append(Check("gstin", bool(reading.gstins), "" if reading.gstins else "No valid GSTIN was found on the invoice."))
    checks.append(Check("invoice_no", bool(reading.invoice_no), "" if reading.invoice_no else "The invoice number could not be found."))
    date_ok = reading.invoice_date is not None and EARLIEST_INVOICE_DATE <= reading.invoice_date <= today + datetime.timedelta(days=1)
    checks.append(Check("invoice_date", date_ok, "" if date_ok else "The invoice date is missing or not a plausible one."))
    return checks
