"""The Balance Sheet and Statement of Profit and Loss in the ICAI format for non-corporate entities.

The format is ICAI's Guidance Note on Financial Statements of Non-Corporate Entities (August 2023): a vertical Balance Sheet
(Owners' funds and liabilities, then assets, each split current and non-current), a Statement of Profit and Loss in five
expense heads, the previous year beside the current one, and a note number on every line.

**Nothing here is stored.** Which line a ledger sits on is worked out for each year from the ledger's group, its name, and
the sign of its balance *that year* -- so a party that owed money one year and was owed it the next lands on a liability line
one year and an asset line the other, each correctly, and the change is reported as a regrouping rather than hidden.
A ledger's own ``nce_line`` (set in the chart) overrides all of that. Profit never changes by regrouping, only presentation.

The ledgers behind every line are the notes (``Note.rows``), each with both years, so a figure can always be taken apart.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace

from classify.models import LedgerAccount, LedgerGroup, Party
from core.money import format_inr
from ledger import nce_assets
from ledger.nce_ageing import outstanding_bills, split_by_age
from ledger.nce_cashflow import cash_flow
from ledger.reports import OPENING_DIFFERENCE, PROFIT_BROUGHT_FORWARD, LedgerBalance, _balances

# ---------------------------------------------------------------------------
# The lines of the two statements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineDef:
    code: str
    label: str
    note: int | None
    #: "L" an equity or liability line (shown as credit balances), "A" an asset line (debit balances), "PI" income, "PE" expense.
    side: str


LINES: dict[str, LineDef] = {
    d.code: d
    for d in [
        LineDef("EQ.CAP", "Owners' Capital Account", 3, "L"),
        LineDef("EQ.RES", "Reserves and surplus", 4, "L"),
        LineDef("NCL.BORR", "Long-term borrowings", 5, "L"),
        LineDef("NCL.DTL", "Deferred tax liabilities (Net)", 6, "L"),
        LineDef("NCL.OTH", "Other long-term liabilities", 7, "L"),
        LineDef("NCL.PROV", "Long-term provisions", 8, "L"),
        LineDef("CL.BORR", "Short-term borrowings", 5, "L"),
        LineDef("CL.PAY", "Trade payables", 9, "L"),
        LineDef("CL.OTH", "Other current liabilities", 10, "L"),
        LineDef("CL.PROV", "Short-term provisions", 8, "L"),
        LineDef("NCA.PPE", "Property, Plant and Equipment", 11, "A"),
        LineDef("NCA.INTANG", "Intangible assets", 11, "A"),
        LineDef("NCA.CWIP", "Capital work in progress", 11, "A"),
        LineDef("NCA.IAUD", "Intangible asset under development", 11, "A"),
        LineDef("NCA.INV", "Non-current investments", 12, "A"),
        LineDef("NCA.DTA", "Deferred tax assets (Net)", 6, "A"),
        LineDef("NCA.LOANS", "Long Term Loans and Advances", 13, "A"),
        LineDef("NCA.OTH", "Other non-current assets", 14, "A"),
        LineDef("CA.INV", "Current investments", 12, "A"),
        LineDef("CA.STOCK", "Inventories", 15, "A"),
        LineDef("CA.REC", "Trade receivables", 16, "A"),
        LineDef("CA.CASH", "Cash and bank balances", 17, "A"),
        LineDef("CA.LOANS", "Short Term Loans and Advances", 13, "A"),
        LineDef("CA.OTH", "Other current assets", 18, "A"),
        LineDef("PL.REV", "Revenue from operations", 19, "PI"),
        LineDef("PL.OTH", "Other Income", 20, "PI"),
        LineDef("PL.COGS", "Cost of goods sold", 21, "PE"),
        LineDef("PL.EMP", "Employee benefits expense", 22, "PE"),
        LineDef("PL.FIN", "Finance costs", 23, "PE"),
        LineDef("PL.DEP", "Depreciation and amortization expense", 24, "PE"),
        LineDef("PL.EXP", "Other expenses", 25, "PE"),
        LineDef("PL.PREM", "Partners' remuneration", None, "PE"),
        LineDef("PL.TAXC", "Current tax", None, "PE"),
        LineDef("PL.TAXD", "Deferred tax charge/ (benefit)", 6, "PE"),
    ]
}

NOTE_TITLES = {
    3: "Owners' Capital Account", 4: "Reserves and surplus", 5: "Borrowings", 6: "Deferred tax", 7: "Other long-term liabilities",
    8: "Provisions", 9: "Trade payables", 10: "Other current liabilities", 11: "Property, Plant and Equipment and Intangible assets",
    12: "Investments", 13: "Loans and advances", 14: "Other non-current assets", 15: "Inventories", 16: "Trade receivables",
    17: "Cash and bank balances", 18: "Other current assets", 19: "Revenue from operations", 20: "Other income",
    21: "Cost of goods sold", 22: "Employee benefits expense", 23: "Finance costs", 24: "Depreciation and amortization expense",
    25: "Other expenses",
}

#: The lines a person may place a ledger on by hand: every balance-sheet and profit-and-loss line.
ASSIGNABLE = tuple(LINES)

_NAME = {
    "premun": re.compile(r"partner'?s?\W*(remuneration|salary|interest)|remuneration (to|of) partner", re.I),
    "tax": re.compile(r"\b(income|provision for)\W*tax\b|current tax|advance tax paid", re.I),
    "deftax": re.compile(r"deferred tax", re.I),
    "dep": re.compile(r"depreciation|amorti[sz]ation", re.I),
    "emp": re.compile(r"salar|wage|bonus|staff|employee|provident|\bpf\b|\besi\b|gratuity|labou?r", re.I),
    "fin": re.compile(r"\binterest\b.*\b(paid|on|expense)|finance (cost|charge)|loan processing|interest (on|to)", re.I),
    "od": re.compile(r"overdraft|\bo/?d\b|cash credit|\bcc\b|working capital|short.?term", re.I),
    "intang": re.compile(r"software|goodwill|patent|trade ?mark|licen[cs]e|copyright|intangible", re.I),
    "cwip": re.compile(r"capital work|\bcwip\b", re.I),
    "longloan": re.compile(r"long.?term|term loan|housing|vehicle loan|car loan", re.I),
    "longadv": re.compile(r"long.?term|security deposit|deposit", re.I),
}


def _place(row: LedgerBalance, override: str = "") -> str:
    """The line this ledger sits on this year: its own setting, else its group and name and the sign of its balance."""
    if override in LINES:
        return override
    group, name, net = row.group, row.name, row.net_paise
    debit = net > 0
    if name == PROFIT_BROUGHT_FORWARD:
        return "EQ.RES"
    if name == OPENING_DIFFERENCE:
        return "EQ.CAP"

    # --- profit and loss
    if group in (LedgerGroup.SALES, LedgerGroup.DIRECT_INCOME):
        return "PL.REV"
    if group == LedgerGroup.INDIRECT_INCOME:
        return "PL.OTH"
    if group in (LedgerGroup.PURCHASE, LedgerGroup.DIRECT_EXPENSE):
        return "PL.COGS"
    if group == LedgerGroup.INDIRECT_EXPENSE:
        for key, line in (("premun", "PL.PREM"), ("deftax", "PL.TAXD"), ("tax", "PL.TAXC"), ("dep", "PL.DEP"), ("emp", "PL.EMP"), ("fin", "PL.FIN")):
            if _NAME[key].search(name):
                return line
        return "PL.EXP"

    # --- balance sheet
    if group == LedgerGroup.CAPITAL:
        return "EQ.CAP"
    if group == LedgerGroup.RESERVES:
        return "EQ.RES"
    if group == LedgerGroup.BANK_OD:
        return "CL.BORR"
    if group == LedgerGroup.LOAN:
        return "CL.BORR" if _NAME["od"].search(name) and not _NAME["longloan"].search(name) else "NCL.BORR"
    if group == LedgerGroup.PROVISION:
        return "NCL.PROV" if _NAME["longloan"].search(name) else "CL.PROV"
    if group == LedgerGroup.CREDITOR:
        return "CA.LOANS" if debit else "CL.PAY"  # an advance paid to a supplier is an asset, whatever the ledger is called
    if group == LedgerGroup.DEBTOR:
        return "CA.REC" if debit or net == 0 else "CL.OTH"  # an advance from a customer is a liability
    if group in (LedgerGroup.DUTIES_AND_TAXES, LedgerGroup.CURRENT_LIABILITY):
        return "CA.OTH" if debit else "CL.OTH"
    if group == LedgerGroup.CURRENT_ASSET:
        return "CA.OTH" if debit or net == 0 else "CL.OTH"
    if group == LedgerGroup.FIXED_ASSET:
        if _NAME["cwip"].search(name):
            return "NCA.CWIP"
        return "NCA.INTANG" if _NAME["intang"].search(name) else "NCA.PPE"
    if group == LedgerGroup.INVESTMENT:
        return "NCA.INV"
    if group == LedgerGroup.STOCK:
        return "CA.STOCK"
    if group in (LedgerGroup.BANK, LedgerGroup.CASH):
        return "CA.CASH" if debit or net == 0 else "CL.BORR"  # an overdrawn bank account is a borrowing
    if group == LedgerGroup.LOAN_ADVANCE:
        return "NCA.LOANS" if _NAME["longadv"].search(name) and re.search(r"long", name, re.I) else "CA.LOANS"
    if group == LedgerGroup.DEPOSIT:
        return "NCA.LOANS"
    if group == LedgerGroup.MISC_EXPENDITURE:
        return "NCA.OTH"
    # Suspense and anything this code does not know: shown, and warned about, never dropped.
    return "CA.OTH" if debit or net == 0 else "CL.OTH"


# ---------------------------------------------------------------------------
# What the engine returns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteRow:
    label: str
    ledger_id: object
    current_paise: int
    previous_paise: int
    #: The sub-head of the note this row falls under (Note 19: "Sale of services"); blank where the note has none.
    section: str = ""
    #: The sub-head came from the ledger's name falling through to the catch-all, not from a rule or from a person.
    guessed: bool = False


@dataclass(frozen=True)
class Note:
    number: int
    title: str
    rows: tuple[NoteRow, ...]
    #: The sub-heads a ledger in this note can be pinned to.
    choices: tuple[str, ...] = ()

    @property
    def total_current_paise(self) -> int:
        return sum(r.current_paise for r in self.rows)

    @property
    def total_previous_paise(self) -> int:
        return sum(r.previous_paise for r in self.rows)


@dataclass(frozen=True)
class StatementRow:
    key: str
    label: str
    #: ``heading`` (no figures), ``line`` (a figure with a note), ``total``, ``subtotal``.
    kind: str
    level: int = 0
    note: int | None = None
    current_paise: int | None = None
    previous_paise: int | None = None


@dataclass(frozen=True)
class Regrouping:
    ledger_id: object
    name: str
    previous_line: str
    current_line: str
    previous_paise: int
    current_paise: int

    @property
    def text(self) -> str:
        return (
            f"{self.name}: shown under {LINES[self.previous_line].label} last year and under {LINES[self.current_line].label} "
            "this year, because the sign of its balance changed. Profit is not affected; only where it is presented."
        )


@dataclass(frozen=True)
class ScheduleRow:
    label: str
    #: One figure (paise) per column; None leaves the cell empty.
    values: tuple[int | None, ...]
    #: ``line``, ``heading`` (no figures) or ``total``.
    kind: str = "line"


@dataclass(frozen=True)
class Schedule:
    """A table that belongs to a note and is not a list of ledgers: the age of receivables, the MSMED Act split, the asset block."""

    note: int
    title: str
    columns: tuple[str, ...]
    rows: tuple[ScheduleRow, ...]


@dataclass(frozen=True)
class PartnerRow:
    name: str
    share_bp: int
    opening_paise: int
    introduced_paise: int
    remuneration_paise: int
    interest_paise: int
    withdrawals_paise: int
    profit_share_paise: int

    @property
    def closing_paise(self) -> int:
        return (
            self.opening_paise + self.introduced_paise + self.remuneration_paise + self.interest_paise
            - self.withdrawals_paise + self.profit_share_paise
        )


@dataclass(frozen=True)
class CapitalTable:
    """Note 3: each partner's (or the proprietor's) capital account for the year, with the year before in total."""

    rows: tuple[PartnerRow, ...]
    previous: tuple[PartnerRow, ...]
    #: Owners' funds on the balance sheet (capital and reserves).
    owners_funds_paise: int

    def total(self, field: str, previous: bool = False) -> int:
        return sum(getattr(r, field) for r in (self.previous if previous else self.rows))

    @property
    def difference_paise(self) -> int:
        """What the balance sheet's owners' funds are above (+) or below (-) the partners' closing balances."""
        return self.owners_funds_paise - self.total("closing_paise")


@dataclass
class Statements:
    balance_sheet: list[StatementRow]
    profit_and_loss: list[StatementRow]
    notes: list[Note]
    regroupings: list[Regrouping]
    footer: object
    previous_footer: object
    has_previous: bool
    balances: bool
    suspense_paise: int
    unit_paise: int = 100
    unit_label: str = "Rs."
    about: str = ""
    policies: str = ""
    capital: CapitalTable | None = None
    #: Things the person should do before these go out, in words.
    warnings: tuple[str, ...] = ()
    schedules: tuple[Schedule, ...] = ()
    entity_type: str = ""
    #: ``msme`` or ``large``: the person's choice, else what the books suggest.
    size: str = "msme"
    size_suggested: str = "msme"
    size_reason: str = ""
    #: The disclosure that goes with the size, drafted for Note 2.
    size_statement: str = ""
    capital_title: str = "Owners' Capital Account"
    #: The Cash Flow Statement (indirect method). A Large entity must give it; an MSME is exempt but may.
    cash_flow: list[StatementRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# What the books cannot say: settings kept on the client
# ---------------------------------------------------------------------------

#: Rounding choices: ``(paise in one unit, how the statements say so)``.
UNITS: dict[str, tuple[int, str]] = {
    "rupees": (100, "Rs."),
    "hundreds": (10_000, "Rs. in hundreds"),
    "thousands": (100_000, "Rs. in thousands"),
    "lakhs": (10_000_000, "Rs. in lakhs"),
    "crores": (1_000_000_000, "Rs. in crores"),
}

_TEXT_MAX = 8000
ENTITY_TYPES = ("proprietor", "partnership", "other")
#: Figures a person enters for a year: the part of old receivables that is doubtful, and the MSMED Act interest disclosures.
YEAR_AMOUNTS = ("receivables_doubtful_paise", "msme_interest_due_paise", "msme_interest_paid_paise", "msme_delay_interest_paise", "msme_further_interest_paise")
CAPITAL_TITLE = {"proprietor": "Proprietor's Capital Account", "partnership": "Partners' Capital Accounts", "other": "Owners' Capital Account", "": "Owners' Capital Account"}
#: Criteria for an MSME (ICAI Announcement on the classification of non-company entities): turnover up to Rs 250 crore in the
#: preceding year, borrowings never above Rs 50 crore, not a bank, financial institution or insurer, and no parent or
#: subsidiary that is not itself an MSME.
MSME_TURNOVER_PAISE = 250 * 10_000_000 * 100
MSME_BORROWINGS_PAISE = 50 * 10_000_000 * 100


def suggest_size(turnover_paise: int, borrowings_paise: int, *, bank_or_insurer: bool = False, non_msme_group: bool = False) -> tuple[str, str]:
    """``("msme" | "large", why)`` from the books and two answers only a person can give."""
    if bank_or_insurer:
        return "large", "A bank, financial institution or insurance company is not an MSME."
    if non_msme_group:
        return "large", "An entity that is a holding or subsidiary of one that is not an MSME is not an MSME."
    if turnover_paise > MSME_TURNOVER_PAISE:
        return "large", "Turnover in the preceding year is above Rs 250 crore."
    if borrowings_paise > MSME_BORROWINGS_PAISE:
        return "large", "Borrowings are above Rs 50 crore."
    return "msme", "Turnover is up to Rs 250 crore and borrowings up to Rs 50 crore."


SIZE_STATEMENT = {
    "msme": "The entity is a Micro, Small and Medium Sized Entity (MSME) as defined in the Announcement of the Institute of Chartered Accountants of India on the criteria for classifying non-company entities, and has availed the exemptions and relaxations available to an MSME under the Accounting Standards.",
    "large": "The entity is a Large entity under the Announcement of the Institute of Chartered Accountants of India on the criteria for classifying non-company entities, and complies in full with the Accounting Standards.",
}
_PARTNER_AMOUNTS = ("introduced_paise", "remuneration_paise", "interest_paise", "withdrawals_paise")


def _amount(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def read_settings(client) -> dict:
    """The client's statement settings, always in full shape whatever is stored.

    ``{"about", "policies", "rounding", "years": {"2025": {"closing_stock_paise": int|None,
    "partners": [{"name", "share_bp", "opening_paise": int|None, "introduced_paise", "remuneration_paise",
    "interest_paise", "withdrawals_paise"}]}}}``. Shares are in basis points (5000 is 50%).
    """
    return normalise_settings(client.nce_settings)


def normalise_settings(raw) -> dict:
    """``read_settings`` for a dict that may be anything: what is usable is kept, the rest dropped."""
    raw = raw if isinstance(raw, dict) else {}
    years: dict[str, dict] = {}
    for fy, body in (raw.get("years") or {}).items():
        if not isinstance(body, dict):
            continue
        partners = []
        for p in (body.get("partners") or [])[:50]:
            name = str(p.get("name", "")).strip()[:120] if isinstance(p, dict) else ""
            if not name:
                continue
            partners.append(
                {
                    "name": name,
                    "share_bp": min(_amount(p.get("share_bp")) or 0, 10_000),
                    "opening_paise": _amount(p.get("opening_paise")),
                    **{k: _amount(p.get(k)) or 0 for k in _PARTNER_AMOUNTS},
                }
            )
        years[str(fy)] = {
            "closing_stock_paise": _amount(body.get("closing_stock_paise")),
            "partners": partners,
            **{k: _amount(body.get(k)) or 0 for k in YEAR_AMOUNTS},
        }
    rounding = raw.get("rounding")
    return {
        "entity_type": raw.get("entity_type") if raw.get("entity_type") in ENTITY_TYPES else "",
        "size": raw.get("size") if raw.get("size") in ("msme", "large") else "",
        "bank_or_insurer": bool(raw.get("bank_or_insurer")),
        "non_msme_group": bool(raw.get("non_msme_group")),
        "about": str(raw.get("about", ""))[:_TEXT_MAX],
        "policies": str(raw.get("policies", ""))[:_TEXT_MAX],
        "rounding": rounding if rounding in UNITS else "rupees",
        "years": years,
    }


# ---------------------------------------------------------------------------
# Sub-heads inside the notes, from the ledger's name and group
# ---------------------------------------------------------------------------

_I = re.IGNORECASE
#: Income that belongs under investing activities in the cash flow, not operating.
_INTEREST_INCOME = re.compile(r"interest|dividend", re.IGNORECASE)
_RELATED = r"director|partner|proprietor|relative|related|promoter|family"
_BANKISH = r"bank|hdfc|sbi|icici|axis|kotak|pnb|canara|idfc|yes bank|bob\b|union bank"

#: ``note -> [(sub-head, name pattern)]`` in the order they print. A ledger takes the first that matches; the last entry is
#: where it lands when none does.
_SECTIONS: dict[int, list[tuple[str, str]]] = {
    19: [
        ("Other operating revenue", r"scrap|drawback|export incentive|subsidy|grant|incentive"),
        ("Sale of services", r"service|commission|fee|consult|job ?work|labou?r charges|professional"),
        ("Sale of products", r""),
    ],
    20: [
        ("Interest income", r"interest"),
        ("Dividend income", r"dividend"),
        ("Net gain/loss on sale of investments", r"investment|mutual fund|capital gain|profit on sale"),
        ("Other non-operating income", r""),
    ],
    21: [
        ("Purchases of stock-in-trade", r"purchase"),
        ("Changes in inventories", r"^\(increase\)"),
        ("Direct expenses", r""),
    ],
    22: [
        ("Contribution to provident and other funds", r"provident|\bpf\b|\besi\b|gratuity|\bepf\b|superannuation"),
        ("Staff welfare expenses", r"welfare|canteen|uniform|training"),
        ("Salaries, wages and bonus", r""),
    ],
    23: [
        ("Other borrowing costs", r"processing|loan (fee|charge)|guarantee|commitment"),
        ("Interest expense", r""),
    ],
    24: [("Amortization", r"amorti"), ("Depreciation", r"")],
    25: [
        ("Payments to auditors", r"audit"),
        ("Rent", r"\brent\b|lease rent"),
        ("Power and fuel", r"electric|power|fuel|diesel|petrol|water"),
        ("Repairs and maintenance", r"repair|maintenance|\bamc\b"),
        ("Insurance", r"insur"),
        ("Rates and taxes", r"rates|\btax\b|licen|penalt|\broc\b"),
        ("Legal and professional fees", r"legal|professional|consult"),
        ("Travelling and conveyance", r"travel|conveyance|taxi|\bcab\b|flight|hotel"),
        ("Communication", r"telephone|mobile|internet|broadband|postage|courier|communication"),
        ("Printing and stationery", r"printing|stationery"),
        ("Advertising and selling expenses", r"advertis|marketing|promotion|commission|brokerage|selling|discount allowed"),
        ("Bank charges", r"bank charge|bank fee"),
        ("Bad debts and provisions for doubtful debts", r"bad debt|written off|doubtful"),
        ("Donations", r"donat|\bcsr\b"),
        ("Miscellaneous expenses", r""),
    ],
    10: [
        ("Interest accrued on borrowings", r"interest accrued|interest payable"),
        ("Income received in advance", r"advance (from|received)|income received|unearned"),
        ("Goods and Service tax payable", r"\bgst\b|igst|cgst|sgst|output"),
        ("TDS payable", r"\btds\b|\btcs\b"),
        ("Statutory dues (PF, ESI, professional tax and others)", r"\bpf\b|\besi\b|provident|professional tax|statutory|payroll"),
        ("Salaries and other employee payables", r"salar|wage|bonus|staff"),
        ("Other payables", r""),
    ],
    18: [
        ("Balances with government authorities", r"\bgst\b|input|\btds\b|\btcs\b|advance tax|\bitc\b|duty|refund"),
        ("Prepaid expenses", r"prepaid"),
        ("Interest accrued", r"accrued|interest receivable"),
        ("Other", r""),
    ],
    15: [
        ("Raw materials", r"raw material"),
        ("Work-in-progress", r"work.?in.?progress|\bwip\b"),
        ("Finished goods", r"finished"),
        ("Stores and spares", r"stores|spares"),
        ("Stock-in-trade", r""),
    ],
    11: [
        ("Land", r"\bland\b"),
        ("Buildings", r"building|premises|factory|godown|shed"),
        ("Plant and machinery", r"plant|machine|equipment|tools"),
        ("Furniture and fixtures", r"furniture|fixture"),
        ("Vehicles", r"vehicle|car\b|truck|scooter|bike|motor"),
        ("Computers", r"computer|laptop|server|printer"),
        ("Office equipment", r"office|\bac\b|air.?condition|phone|cctv"),
        ("Intangible assets", r"software|goodwill|patent|trade ?mark|licen[cs]e|copyright|intangible"),
        ("Capital work in progress", r"capital work|\bcwip\b"),
        ("Other property, plant and equipment", r""),
    ],
    12: [
        ("Investments in partnership firms", r"partnership|\bllp\b|firm"),
        ("Investments in mutual funds", r"mutual|\bmf\b|\bsip\b"),
        ("Investments in equity instruments", r"equity|shares?\b|stock"),
        ("Investments in government securities, debentures and bonds", r"government|debenture|bond|\bgsec\b"),
        ("Investment property", r"property|land"),
        ("Other investments", r""),
    ],
    17: [
        ("Cash on hand", r"\bcash\b"),
        ("Deposits with banks", r"fixed deposit|\bfd\b|\bfdr\b|term deposit|margin"),
        ("Balances with banks", r""),
    ],
}


KINDS_5 = ("Term loans from banks", "Term loans from other parties", "Loans repayable on demand", "Loans and advances from related parties", "Other loans and advances")
KINDS_8 = ("Provision for employee benefits", "Provision for income tax", "Other provisions")
KINDS_13 = ("Security deposits", "Loans and advances to related parties", "Advances to suppliers and others")
#: Notes whose sub-head is prefixed with the horizon ("Long-term · Term loans from banks").
_HORIZON_NOTES = (5, 8, 13)
#: Where a ledger that matches no rule falls to the catch-all, a person should look.
_GUESS_NOTES = (10, 11, 12, 15, 18, 20, 25)


def _tail_choices(note: int) -> tuple[str, ...]:
    if note == 5:
        return KINDS_5
    if note == 8:
        return KINDS_8
    if note == 13:
        return KINDS_13
    return tuple(label for label, _ in _SECTIONS.get(note, []) if label != "Changes in inventories")


def section_choices() -> dict[int, tuple[str, ...]]:
    return {n: c for n in (5, 8, 10, 11, 12, 13, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25) if (c := _tail_choices(n))}


def all_section_choices() -> frozenset[str]:
    return frozenset(label for labels in section_choices().values() for label in labels)


def _matches(note: int, name: str, *, skip_first: bool = False) -> bool:
    rules = _SECTIONS[note][1:] if skip_first else _SECTIONS[note]
    return any(pattern and re.search(pattern, name, _I) for _, pattern in rules)


def _pick(note: int, name: str, *, strict: bool = False, skip_first: bool = False) -> str:
    rules = _SECTIONS[note][1:] if skip_first else _SECTIONS[note]
    for label, pattern in rules:
        if pattern and re.search(pattern, name, _I):
            return label
    return "" if strict else rules[-1][0]


def _section(note: int | None, code: str, row: LedgerBalance, pinned: str = "") -> tuple[str, bool]:
    """``(the sub-head of the note this ledger is listed under, whether that was a guess)``; blank where the note has none."""
    name, group = row.name, row.group
    horizon = "Long-term" if code.startswith("NC") else "Short-term"
    if note is None:
        return "", False
    if pinned and pinned in _tail_choices(note):
        if note in _HORIZON_NOTES:
            return f"{horizon} · {pinned}", False
        if note == 12:
            return f"{'Current' if code.startswith('CA') else 'Non-current'} · {pinned}", False
        return pinned, False
    guessed = note in _GUESS_NOTES and note in _SECTIONS and not _matches(note, name)
    if note == 5:
        secured = " (unsecured)" if re.search(r"unsecured", name, _I) else " (secured)" if re.search(r"secured", name, _I) else ""
        if re.search(_RELATED, name, _I):
            kind = KINDS_5[3]
        elif group == LedgerGroup.BANK_OD or re.search(r"overdraft|\bo/?d\b|cash credit|\bcc\b", name, _I):
            kind = KINDS_5[2]
        elif re.search(r"term loan|housing|vehicle|car loan|equipment", name, _I):
            kind = KINDS_5[0] if re.search(_BANKISH, name, _I) else KINDS_5[1]
        else:
            kind = KINDS_5[4]
        return f"{horizon} · {kind}{secured}", kind == KINDS_5[4]
    if note == 8:
        if re.search(r"gratuity|leave|encash|bonus|\bpf\b|employee", name, _I):
            return f"{horizon} · {KINDS_8[0]}", False
        if re.search(r"tax", name, _I):
            return f"{horizon} · {KINDS_8[1]}", False
        return f"{horizon} · {KINDS_8[2]}", True
    if note == 13:
        if re.search(r"deposit", name, _I):
            return f"{horizon} · {KINDS_13[0]}", False
        if re.search(_RELATED, name, _I):
            return f"{horizon} · {KINDS_13[1]}", False
        return f"{horizon} · {KINDS_13[2]}", False
    if note == 12:
        return f"{'Current' if code.startswith('CA') else 'Non-current'} · {_pick(12, name)}", guessed
    if note == 19:
        return _pick(19, name, strict=True) or ("Sale of services" if group == LedgerGroup.DIRECT_INCOME else "Sale of products"), False
    if note == 21:
        return ("Purchases of stock-in-trade" if group == LedgerGroup.PURCHASE else _pick(21, name)), False
    if note == 17:
        return ("Cash on hand" if group == LedgerGroup.CASH else _pick(17, name, skip_first=True)), False
    if note in _SECTIONS:
        return _pick(note, name), guessed
    return "", False


def _section_rank(note: int, section: str) -> int:
    """Where a sub-head prints: the order of the note's rules, long-term before short-term."""
    order = [label for label, _ in _SECTIONS.get(note, [])]
    tail = section.split(" · ")[-1]
    rank = order.index(tail) if tail in order else len(order)
    return rank + (0 if section.startswith(("Long-term", "Non-current")) else 100)


# ---------------------------------------------------------------------------
# Closing stock, the partners' capital table, rounding
# ---------------------------------------------------------------------------


def _stock_gap(rows, settings: dict, fy: int) -> int:
    """Closing stock entered for the year less what the stock ledgers carry; nothing when none is entered."""
    entered = settings["years"].get(str(fy), {}).get("closing_stock_paise")
    if entered is None:
        return 0
    return entered - sum(r.net_paise for r in rows if r.group == LedgerGroup.STOCK)


def _partners(settings: dict, fy: int, profit: int, opening_by_name: dict[str, int]) -> tuple[PartnerRow, ...]:
    entered = settings["years"].get(str(fy), {}).get("partners") or []
    if not entered:
        return ()
    # The profit is split by share to the paisa: whatever the shares leave over goes to the first partner.
    shares = [profit * p["share_bp"] // 10_000 for p in entered]
    if sum(p["share_bp"] for p in entered) == 10_000:
        shares[0] += profit - sum(shares)
    return tuple(
        PartnerRow(
            name=p["name"],
            share_bp=p["share_bp"],
            opening_paise=p["opening_paise"] if p["opening_paise"] is not None else opening_by_name.get(p["name"], 0),
            introduced_paise=p["introduced_paise"],
            remuneration_paise=p["remuneration_paise"],
            interest_paise=p["interest_paise"],
            withdrawals_paise=p["withdrawals_paise"],
            profit_share_paise=share,
        )
        for p, share in zip(entered, shares, strict=True)
    )


def _unit(paise: int, unit: int) -> int:
    """``paise`` rounded half away from zero to a whole ``unit``."""
    if unit == 100:
        return paise
    whole = (abs(paise) + unit // 2) // unit * unit
    return whole if paise >= 0 else -whole


def _signed(line: LineDef, net: int) -> int:
    """A ledger's contribution to its line: assets and expenses as debits, liabilities and income as credits."""
    return net if line.side in ("A", "PE") else -net


def _synthetic(name: str, group: str) -> LedgerBalance:
    """A line that is not a ledger (the closing stock someone entered), shown in a note with no ledger to open."""
    return LedgerBalance(name=name, group=group, debit_paise=0, credit_paise=0)


def _tally(rows, overrides, unit: int = 100) -> tuple[dict, dict]:
    """``(line code -> paise, line code -> [(row, paise)])`` for one year.

    Each ledger's contribution is rounded to ``unit`` *here*, before anything is added, so a line, its note, the profit and
    the totals are all sums of the same rounded figures and cannot drift apart.
    """
    totals: dict[str, int] = {}
    parts: dict[str, list] = {}
    for row in rows:
        code = _place(row, overrides.get(row.ledger_id, ""))
        paise = _unit(_signed(LINES[code], row.net_paise), unit)
        totals[code] = totals.get(code, 0) + paise
        parts.setdefault(code, []).append((row, paise))
    return totals, parts


def build(client, financial_year: int) -> Statements:
    """Both statements for ``financial_year`` with the year before it, the notes, and any regrouping between the two."""
    overrides = dict(
        LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).exclude(nce_line="").values_list("pk", "nce_line")
    )
    pins = dict(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).exclude(nce_section="").values_list("pk", "nce_section"))
    cur_rows, footer = _balances(client, financial_year)
    prev_rows, prev_footer = _balances(client, financial_year - 1)
    settings = read_settings(client)
    unit, unit_label = UNITS[settings["rounding"]]
    entity_type = settings["entity_type"]
    capital_title = CAPITAL_TITLE[entity_type]
    cur, cur_parts = _tally(cur_rows, overrides, unit)
    prev, prev_parts = _tally(prev_rows, overrides, unit)

    # Closing stock the person entered, where the stock ledgers do not carry it. It raises Inventories, lowers the cost of
    # goods sold by the year's change, and the whole of it sits in Reserves, so the sheet still balances.
    gap_c, gap_p = _unit(_stock_gap(cur_rows, settings, financial_year), unit), _unit(_stock_gap(prev_rows, settings, financial_year - 1), unit)
    gap_pp = _unit(_stock_gap(_balances(client, financial_year - 2)[0], settings, financial_year - 2), unit) if settings["years"].get(str(financial_year - 2), {}).get("closing_stock_paise") is not None else 0
    for totals, parts, gap, change in ((cur, cur_parts, gap_c, gap_c - gap_p), (prev, prev_parts, gap_p, gap_p - gap_pp)):
        if gap:
            totals["CA.STOCK"] = totals.get("CA.STOCK", 0) + gap
            parts.setdefault("CA.STOCK", []).append((_synthetic("Closing stock as valued at the year end", LedgerGroup.STOCK), gap))
        if change:
            totals["PL.COGS"] = totals.get("PL.COGS", 0) - change
            parts.setdefault("PL.COGS", []).append((_synthetic("(Increase)/decrease in inventories", LedgerGroup.DIRECT_EXPENSE), -change))

    def profit(totals: dict) -> dict:
        revenue, other = totals.get("PL.REV", 0), totals.get("PL.OTH", 0)
        expenses = sum(totals.get(c, 0) for c in ("PL.COGS", "PL.EMP", "PL.FIN", "PL.DEP", "PL.EXP"))
        before_tax_items = revenue + other - expenses
        after_prem = before_tax_items - totals.get("PL.PREM", 0)
        tax = totals.get("PL.TAXC", 0) + totals.get("PL.TAXD", 0)
        return {"income": revenue + other, "expenses": expenses, "before": before_tax_items, "after_prem": after_prem, "tax": tax, "net": after_prem - tax}

    cur_p, prev_p = profit(cur), profit(prev)

    def v(totals, code, extra=0):
        return totals.get(code, 0) + extra

    # The year's result is part of Reserves and surplus, so the sheet balances without anyone transferring it.
    cur_res = v(cur, "EQ.RES", cur_p["net"] + gap_p)
    prev_res = v(prev, "EQ.RES", prev_p["net"] + gap_pp)

    def L(key, label, *, level=0, note=None, c=None, p=None, kind="line"):
        return StatementRow(key, label, kind, level, note, c, p)

    def line(code, *, level=1, key=None, label=None, current=None, previous=None):
        d = LINES[code]
        return L(key or code, label or d.label, level=level, note=d.note, c=cur.get(code, 0) if current is None else current, p=prev.get(code, 0) if previous is None else previous)

    def total(key, label, c, p, level=0):
        return L(key, label, level=level, c=c, p=p, kind="total")

    nc_liab = ("NCL.BORR", "NCL.DTL", "NCL.OTH", "NCL.PROV")
    c_liab = ("CL.BORR", "CL.PAY", "CL.OTH", "CL.PROV")
    nca = ("NCA.PPE", "NCA.INTANG", "NCA.CWIP", "NCA.IAUD", "NCA.INV", "NCA.DTA", "NCA.LOANS", "NCA.OTH")
    ca = ("CA.INV", "CA.STOCK", "CA.REC", "CA.CASH", "CA.LOANS", "CA.OTH")

    def s(totals, codes):
        return sum(totals.get(c, 0) for c in codes)

    owners_c, owners_p = v(cur, "EQ.CAP") + cur_res, v(prev, "EQ.CAP") + prev_res
    liab_c = owners_c + s(cur, nc_liab) + s(cur, c_liab)
    liab_p = owners_p + s(prev, nc_liab) + s(prev, c_liab)
    assets_c = s(cur, nca) + s(cur, ca)
    assets_p = s(prev, nca) + s(prev, ca)
    # Rounding every ledger can leave the two sides a few units apart; the gap is shown as one line, never buried.
    rnd_c, rnd_p = (assets_c - liab_c, assets_p - liab_p) if unit != 100 else (0, 0)
    owners_c, owners_p, liab_c, liab_p = owners_c + rnd_c, owners_p + rnd_p, liab_c + rnd_c, liab_p + rnd_p

    # --- the Cash Flow Statement: this year from the two year-end positions, last year from the one before that
    def interest_of(parts) -> int:
        return sum(p for r, p in parts.get("PL.OTH", []) if _INTEREST_INCOME.search(r.name))

    if prev_rows:
        pp_rows, _ = _balances(client, financial_year - 2)
        pp, _pp_parts = _tally(pp_rows, overrides, unit)
        stock_years = settings["years"]
        gap_ppp = (
            _unit(_stock_gap(_balances(client, financial_year - 3)[0], settings, financial_year - 3), unit)
            if stock_years.get(str(financial_year - 3), {}).get("closing_stock_paise") is not None
            else 0
        )
        if gap_pp:
            pp["CA.STOCK"] = pp.get("CA.STOCK", 0) + gap_pp
        if gap_pp - gap_ppp:
            pp["PL.COGS"] = pp.get("PL.COGS", 0) - (gap_pp - gap_ppp)
        pp_p = profit(pp)
        owners_pp = v(pp, "EQ.CAP") + v(pp, "EQ.RES", pp_p["net"] + gap_ppp)
    else:
        pp, pp_p, owners_pp = {}, profit({}), 0
    cf_args = {"show_difference": False}
    cf_cur = cash_flow(
        cur, prev, profit_before_tax=cur_p["after_prem"], net_profit=cur_p["net"], interest_income=interest_of(cur_parts),
        owners_funds_cur=owners_c, owners_funds_prev=owners_p, **cf_args,
    )
    cf_prev = cash_flow(
        prev, pp, profit_before_tax=prev_p["after_prem"], net_profit=prev_p["net"], interest_income=interest_of(prev_parts),
        owners_funds_cur=owners_p, owners_funds_prev=owners_pp, **cf_args,
    )
    if cf_cur.unexplained_paise or cf_prev.unexplained_paise:
        cf_args["show_difference"] = True
        cf_cur = cash_flow(
            cur, prev, profit_before_tax=cur_p["after_prem"], net_profit=cur_p["net"], interest_income=interest_of(cur_parts),
            owners_funds_cur=owners_c, owners_funds_prev=owners_p, **cf_args,
        )
        cf_prev = cash_flow(
            prev, pp, profit_before_tax=prev_p["after_prem"], net_profit=prev_p["net"], interest_income=interest_of(prev_parts),
            owners_funds_cur=owners_p, owners_funds_prev=owners_pp, **cf_args,
        )
    before = {r.key: r.paise for r in cf_prev.rows}
    cash_rows = [
        StatementRow(r.key, r.label, r.kind, r.level, None, None if r.kind == "heading" else r.paise, None if r.kind == "heading" else before.get(r.key, 0))
        for r in cf_cur.rows
    ]

    bs = [
        L("h.I", "I. OWNERS' FUNDS AND LIABILITIES", kind="heading"),
        L("h.1", "(1) Owners' Funds", level=1, kind="heading"),
        line("EQ.CAP", level=2, label=capital_title),
        L("EQ.RES", "Reserves and surplus", level=2, note=4, c=cur_res, p=prev_res),
        *([L("EQ.RND", "Rounding difference", level=2, c=rnd_c, p=rnd_p)] if rnd_c or rnd_p else []),
        total("t.1", "Owners' Funds", owners_c, owners_p, 1),
        L("h.2", "(2) Non-current liabilities", level=1, kind="heading"),
        *[line(c, level=2) for c in nc_liab],
        total("t.2", "Non-current liabilities", s(cur, nc_liab), s(prev, nc_liab), 1),
        L("h.3", "(3) Current liabilities", level=1, kind="heading"),
        *[line(c, level=2) for c in c_liab],
        total("t.3", "Current liabilities", s(cur, c_liab), s(prev, c_liab), 1),
        total("t.L", "TOTAL", liab_c, liab_p),
        L("h.II", "II. ASSETS", kind="heading"),
        L("h.a1", "(1) Non-current assets", level=1, kind="heading"),
        L("h.ppe", "(a) Property, Plant and Equipment and Intangible assets", level=2, kind="heading"),
        *[line(c, level=3) for c in ("NCA.PPE", "NCA.INTANG", "NCA.CWIP", "NCA.IAUD")],
        *[line(c, level=2) for c in ("NCA.INV", "NCA.DTA", "NCA.LOANS", "NCA.OTH")],
        total("t.a1", "Non-current assets", s(cur, nca), s(prev, nca), 1),
        L("h.a2", "(2) Current assets", level=1, kind="heading"),
        *[line(c, level=2) for c in ca],
        total("t.a2", "Current assets", s(cur, ca), s(prev, ca), 1),
        total("t.A", "TOTAL", assets_c, assets_p),
    ]

    def pl_line(code, level=1, label=None):
        return line(code, level=level, label=label)

    income_c, income_p = cur_p["income"], prev_p["income"]
    pl = [
        L("PL.REV", "Revenue from operations", note=19, c=cur.get("PL.REV", 0), p=prev.get("PL.REV", 0)),
        L("PL.OTH", "Other Income", note=20, c=cur.get("PL.OTH", 0), p=prev.get("PL.OTH", 0)),
        total("t.inc", "Total Income (I + II)", income_c, income_p),
        L("h.exp", "Expenses:", kind="heading"),
        pl_line("PL.COGS", label="(a) Cost of goods sold"),
        pl_line("PL.EMP"),
        pl_line("PL.FIN"),
        pl_line("PL.DEP"),
        pl_line("PL.EXP"),
        total("t.exp", "Total expenses", cur_p["expenses"], prev_p["expenses"]),
        total("t.V", "Profit/(loss) before exceptional and extraordinary items, partners' remuneration and tax (III - IV)", cur_p["before"], prev_p["before"]),
        L("PL.EXC", "Exceptional items", level=1, c=0, p=0),
        L("PL.EXT", "Extraordinary items", level=1, c=0, p=0),
        total("t.IX", "Profit before partners' remuneration and tax", cur_p["before"], prev_p["before"]),
        L("PL.PREM", "Partners' remuneration", level=1, c=cur.get("PL.PREM", 0), p=prev.get("PL.PREM", 0)),
        total("t.XI", "Profit before tax", cur_p["after_prem"], prev_p["after_prem"]),
        L("h.tax", "Tax expense:", kind="heading"),
        L("PL.TAXC", "(a) Current tax", level=1, c=cur.get("PL.TAXC", 0), p=prev.get("PL.TAXC", 0)),
        L("PL.TAXD", "(c) Deferred tax charge/ (benefit)", level=1, note=6, c=cur.get("PL.TAXD", 0), p=prev.get("PL.TAXD", 0)),
        total("t.XVII", "Profit/(Loss) for the year", cur_p["net"], prev_p["net"]),
    ]

    # --- the notes: every line's ledgers, both years
    notes: dict[int, list[NoteRow]] = {}

    def add(code: str, rows_by_year: tuple[dict, dict]):
        d = LINES[code]
        if d.note is None:
            return
        cur_map = {r.ledger_id or r.name: (r, p) for r, p in rows_by_year[0].get(code, [])}
        prev_map = {r.ledger_id or r.name: (r, p) for r, p in rows_by_year[1].get(code, [])}
        for key in {**cur_map, **prev_map}:
            row = (cur_map.get(key) or prev_map.get(key))[0]
            section, guessed = _section(d.note, code, row, pins.get(row.ledger_id, ""))
            notes.setdefault(d.note, []).append(
                NoteRow(row.name, row.ledger_id, cur_map.get(key, (None, 0))[1], prev_map.get(key, (None, 0))[1], section, guessed)
            )

    for code in LINES:
        add(code, (cur_parts, prev_parts))
    notes.setdefault(4, []).append(NoteRow("Surplus in Statement of Profit and Loss for the year", None, cur_p["net"], prev_p["net"]))
    if gap_p or gap_pp:
        notes[4].append(NoteRow("Closing stock of earlier years, valued at the year end and not in the ledgers", None, gap_p, gap_pp))
    for number, rows in notes.items():
        rows.sort(key=lambda r: (_section_rank(number, r.section), r.section, r.label.lower()))
    choices = section_choices()
    note_list = [Note(n, capital_title if n == 3 else NOTE_TITLES[n], tuple(rows), choices.get(n, ())) for n, rows in sorted(notes.items())]

    # --- a ledger that moved from one line to another between the two years
    regroupings = []
    cur_by = {r.ledger_id: _place(r, overrides.get(r.ledger_id, "")) for r in cur_rows if r.ledger_id}
    prev_by = {r.ledger_id: _place(r, overrides.get(r.ledger_id, "")) for r in prev_rows if r.ledger_id}
    names = {r.ledger_id: r for r in (*prev_rows, *cur_rows) if r.ledger_id}
    cur_net = {r.ledger_id: r.net_paise for r in cur_rows if r.ledger_id}
    prev_net = {r.ledger_id: r.net_paise for r in prev_rows if r.ledger_id}
    for ledger_id, now in cur_by.items():
        before = prev_by.get(ledger_id)
        if before and before != now and prev_net.get(ledger_id):
            regroupings.append(Regrouping(ledger_id, names[ledger_id].name, before, now, prev_net[ledger_id], cur_net.get(ledger_id, 0)))

    suspense = sum(r.net_paise for r in cur_rows if r.group == LedgerGroup.SUSPENSE)
    has_previous = bool(prev_rows)

    prior = _partners(settings, financial_year - 1, prev_p["net"], {})
    table = _partners(settings, financial_year, cur_p["net"], {p.name: p.closing_paise for p in prior})
    capital = CapitalTable(table, prior, owners_c) if table or prior else None

    warnings = []
    holds_stock = any(r.group == LedgerGroup.STOCK and r.net_paise for r in cur_rows)
    if (holds_stock or cur.get("PL.COGS")) and settings["years"].get(str(financial_year), {}).get("closing_stock_paise") is None:
        warnings.append("Closing stock for this year is not entered, so inventories are shown as the stock ledgers carry them.")
    if capital and abs(capital.difference_paise) > max(100, unit):
        warnings.append("The partners' closing capital does not agree with the owners' funds on the balance sheet. Check Note 3.")
    if not settings["about"].strip() or not settings["policies"].strip():
        warnings.append("Notes 1 and 2 (about the entity and accounting policies) are not written yet.")

    balanced = liab_c == assets_c if unit == 100 else sum(r.net_paise for r in cur_rows) == 0
    if unit != 100:
        if capital:
            def r_partner(p: PartnerRow) -> PartnerRow:
                return replace(p, **{f: _unit(getattr(p, f), unit) for f in ("opening_paise", "introduced_paise", "remuneration_paise", "interest_paise", "withdrawals_paise", "profit_share_paise")})

            capital = CapitalTable(tuple(map(r_partner, capital.rows)), tuple(map(r_partner, capital.previous)), owners_c)
        warnings.append(f"Figures are in {unit_label.removeprefix('Rs. in ')}. Each ledger is rounded before adding up, and what is left over is shown as the Rounding difference.")

    # --- tables that belong to a note
    cols = (f"31 March {financial_year + 1}", f"31 March {financial_year}")
    end_c, end_p = datetime.date(financial_year + 1, 3, 31), datetime.date(financial_year, 3, 31)
    schedules: list[Schedule] = []

    def S(label, c, p, kind="line"):
        return ScheduleRow(label, (c, p), kind)

    def H(label):
        return ScheduleRow(label, (None, None), "heading")

    msme_ledgers = set(Party.objects.filter(firm_id=client.firm_id, client=client, msme=True, ledger__isnull=False).values_list("ledger_id", flat=True))

    def payable(parts, msme):
        return sum(p for r, p in parts.get("CL.PAY", []) if (r.ledger_id in msme_ledgers) == msme)

    pay_c, pay_p = cur.get("CL.PAY", 0), prev.get("CL.PAY", 0)
    if pay_c or pay_p:
        schedules.append(
            Schedule(
                9,
                "Trade payables by kind of supplier",
                cols,
                (
                    S("(a) Total outstanding dues of micro, small and medium enterprises", payable(cur_parts, True), payable(prev_parts, True)),
                    S("(b) Total outstanding dues of creditors other than micro, small and medium enterprises", payable(cur_parts, False), payable(prev_parts, False)),
                    S("Total trade payables", pay_c, pay_p, "total"),
                ),
            )
        )
    year_now, year_before = settings["years"].get(str(financial_year), {}), settings["years"].get(str(financial_year - 1), {})

    def entered(key):
        return _unit(year_now.get(key, 0), unit), _unit(year_before.get(key, 0), unit)

    msme_c, msme_p = payable(cur_parts, True), payable(prev_parts, True)
    if msme_c or msme_p or any(any(entered(k)) for k in YEAR_AMOUNTS[1:]):
        due = entered("msme_interest_due_paise")
        schedules.append(
            Schedule(
                9,
                "Dues to suppliers registered under the MSMED Act, on the information available to the entity",
                cols,
                (
                    H("(a) Amount remaining unpaid to any supplier at the end of the year"),
                    S("Principal", msme_c, msme_p),
                    S("Interest", *due),
                    S("Total", msme_c + due[0], msme_p + due[1], "total"),
                    S("(b) Interest paid under section 16 of the Act, with payments made beyond the appointed day", *entered("msme_interest_paid_paise")),
                    S("(c) Interest due and payable for the delay in payments made beyond the appointed day, without the interest under the Act", *entered("msme_delay_interest_paise")),
                    S("(d) Interest accrued and remaining unpaid at the end of the year", *due),
                    S("(e) Further interest remaining due and payable in the succeeding years", *entered("msme_further_interest_paise")),
                ),
            )
        )

    rec_c, rec_p = cur.get("CA.REC", 0), prev.get("CA.REC", 0)
    if rec_c or rec_p:
        def aged(parts, as_at, doubtful):
            ids = [r.ledger_id for r, _ in parts.get("CA.REC", []) if r.ledger_id]
            under, over = split_by_age(outstanding_bills(client, ids, as_at), as_at)
            under, over = _unit(under, unit), _unit(over, unit)
            doubtful = min(_unit(doubtful, unit), over)
            return under, over - doubtful, doubtful

        under_c, over_c, doubt_c = aged(cur_parts, end_c, year_now.get("receivables_doubtful_paise", 0))
        under_p, over_p, doubt_p = aged(prev_parts, end_p, year_before.get("receivables_doubtful_paise", 0))
        schedules.append(
            Schedule(
                16,
                "Trade receivables by age, counted from the date each was due for receipt",
                cols,
                (
                    H("Outstanding for a period less than 6 months from the date they are due for receipt"),
                    S("(a) Secured, considered good", 0, 0),
                    S("(b) Unsecured, considered good", under_c, under_p),
                    S("(c) Doubtful", 0, 0),
                    H("Outstanding for a period exceeding 6 months from the date they are due for receipt"),
                    S("(a) Secured, considered good", 0, 0),
                    S("(b) Unsecured, considered good", over_c, over_p),
                    S("(c) Doubtful", doubt_c, doubt_p),
                    H("Not set against a bill"),
                    S("Receipts and credits on account, and balances with no bill behind them", rec_c - under_c - over_c - doubt_c, rec_p - under_p - over_p - doubt_p),
                    S("Total trade receivables", rec_c, rec_p, "total"),
                ),
            )
        )
        warnings.append("Trade receivables are shown as unsecured; whether a debt is secured is not recorded. The allowance for doubtful debts, if booked, is in the provisions.")

    # --- Note 11's block from the asset register, and whether the register agrees with the ledgers
    facts = nce_assets.facts_of(client, financial_year, lambda asset: _pick(11, f"{asset.name} {asset.ledger.name}"))
    ledger_fixed = cur.get("NCA.PPE", 0) + cur.get("NCA.INTANG", 0)
    if facts:
        now, before = nce_assets.block_for(facts, financial_year), nce_assets.block_for(facts, financial_year - 1)
        kinds = [label for label, _ in _SECTIONS[11] if label in now or label in before]

        def figures(blocks, field):
            return [_unit(getattr(blocks.get(k, nce_assets.Block()), field), unit) for k in kinds]

        def R(label, vals, kind="line"):
            return ScheduleRow(label, (*vals, sum(vals)), kind)

        def closings(blocks):
            gross = [a + b - c for a, b, c in zip(figures(blocks, "gross_open"), figures(blocks, "additions"), figures(blocks, "deductions"), strict=True)]
            dep = [a + b - c for a, b, c in zip(figures(blocks, "dep_open"), figures(blocks, "dep_year"), figures(blocks, "dep_deductions"), strict=True)]
            return gross, dep, [g - d for g, d in zip(gross, dep, strict=True)]

        gross_c, dep_c, net_c = closings(now)
        _, _, net_p = closings(before)
        head = ScheduleRow
        schedules.append(
            Schedule(
                11,
                "Property, Plant and Equipment and Intangible assets: gross block, depreciation and net block, from the asset register",
                (*kinds, "Total"),
                (
                    head("Gross block", (None,) * (len(kinds) + 1), "heading"),
                    R(f"At 1 April {financial_year}", figures(now, "gross_open")),
                    R("Additions", figures(now, "additions")),
                    R("Deductions/Adjustments", figures(now, "deductions")),
                    R(f"At 31 March {financial_year + 1}", gross_c, "total"),
                    head("Depreciation and amortization", (None,) * (len(kinds) + 1), "heading"),
                    R(f"At 1 April {financial_year}", figures(now, "dep_open")),
                    R("For the year", figures(now, "dep_year")),
                    R("Deductions/Adjustments", figures(now, "dep_deductions")),
                    R(f"At 31 March {financial_year + 1}", dep_c, "total"),
                    head("Net block", (None,) * (len(kinds) + 1), "heading"),
                    R(f"At 31 March {financial_year}", net_p),
                    R(f"At 31 March {financial_year + 1}", net_c, "total"),
                ),
            )
        )
        register_net, register_dep = sum(net_c), sum(figures(now, "dep_year"))
        if abs(register_net - ledger_fixed) > max(100, unit):
            warnings.append(
                f"The asset register's net block ({format_inr(register_net)}) does not agree with the fixed assets in the ledgers ({format_inr(ledger_fixed)}). "
                "Book the year's depreciation from the Assets screen, or register the assets still missing."
            )
        if abs(register_dep - cur.get("PL.DEP", 0)) > max(100, unit):
            warnings.append(
                f"Depreciation by the register ({format_inr(register_dep)}) differs from depreciation in the books ({format_inr(cur.get('PL.DEP', 0))}). Book it from the Assets screen."
            )
    elif ledger_fixed:
        warnings.append(f"Fixed assets of {format_inr(ledger_fixed)} are in the ledgers but not in the asset register, so Note 11 cannot show the block. Register them on the Assets screen.")

    # --- the size of the entity under the accounting standards, and what follows from it
    turnover = prev.get("PL.REV", 0) if has_previous else cur.get("PL.REV", 0)
    borrowings = cur.get("NCL.BORR", 0) + cur.get("CL.BORR", 0)
    size_suggested, size_reason = suggest_size(turnover, borrowings, bank_or_insurer=settings["bank_or_insurer"], non_msme_group=settings["non_msme_group"])
    size = settings["size"] or size_suggested
    if size == "large" and abs(cf_cur.unexplained_paise) > max(100, unit):
        warnings.append(
            f"The Cash Flow Statement has a difference of {format_inr(abs(cf_cur.unexplained_paise))} that the books do not explain. "
            "Usually a ledger is on the wrong line (for example a loan under Other liabilities), or deferred tax is out of step."
        )
    if not entity_type:
        warnings.append("Say whether this is a proprietorship, a partnership or another kind of entity (Statement details).")
    if entity_type == "proprietor" and cur.get("PL.PREM"):
        warnings.append("A proprietor's remuneration is not an expense of the business. Check the ledger shown as Partners' remuneration.")
    guessed = sorted({r.label for n in note_list for r in n.rows if r.guessed})
    if guessed:
        warnings.append(f"{len(guessed)} ledger{'s' if len(guessed) != 1 else ''} sit under a catch-all sub-head by guess. Review them under the notes.")

    return Statements(
        balance_sheet=bs,
        profit_and_loss=pl,
        notes=note_list,
        regroupings=regroupings,
        footer=footer,
        previous_footer=prev_footer,
        has_previous=has_previous,
        balances=balanced,
        suspense_paise=suspense,
        unit_paise=unit,
        unit_label=unit_label,
        about=settings["about"],
        policies=settings["policies"],
        capital=capital,
        warnings=tuple(warnings),
        schedules=tuple(schedules),
        entity_type=entity_type,
        size=size,
        size_suggested=size_suggested,
        size_reason=size_reason,
        size_statement=SIZE_STATEMENT[size],
        capital_title=capital_title,
        cash_flow=cash_rows,
    )
