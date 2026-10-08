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

import re
from dataclasses import dataclass

from classify.models import LedgerAccount, LedgerGroup
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


@dataclass(frozen=True)
class Note:
    number: int
    title: str
    rows: tuple[NoteRow, ...]

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


def _signed(line: LineDef, net: int) -> int:
    """A ledger's contribution to its line: assets and expenses as debits, liabilities and income as credits."""
    return net if line.side in ("A", "PE") else -net


def _tally(rows, overrides) -> tuple[dict, dict]:
    """``(line code -> paise, line code -> [(row, paise)])`` for one year."""
    totals: dict[str, int] = {}
    parts: dict[str, list] = {}
    for row in rows:
        code = _place(row, overrides.get(row.ledger_id, ""))
        paise = _signed(LINES[code], row.net_paise)
        totals[code] = totals.get(code, 0) + paise
        parts.setdefault(code, []).append((row, paise))
    return totals, parts


def build(client, financial_year: int) -> Statements:
    """Both statements for ``financial_year`` with the year before it, the notes, and any regrouping between the two."""
    overrides = dict(
        LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).exclude(nce_line="").values_list("pk", "nce_line")
    )
    cur_rows, footer = _balances(client, financial_year)
    prev_rows, prev_footer = _balances(client, financial_year - 1)
    cur, cur_parts = _tally(cur_rows, overrides)
    prev, prev_parts = _tally(prev_rows, overrides)

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
    cur_res = v(cur, "EQ.RES", cur_p["net"])
    prev_res = v(prev, "EQ.RES", prev_p["net"])

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

    bs = [
        L("h.I", "I. OWNERS' FUNDS AND LIABILITIES", kind="heading"),
        L("h.1", "(1) Owners' Funds", level=1, kind="heading"),
        line("EQ.CAP", level=2),
        L("EQ.RES", "Reserves and surplus", level=2, note=4, c=cur_res, p=prev_res),
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
            # A note that gathers several lines (borrowings, provisions, assets, investments, loans) says which each is.
            label = f"{d.label}: {row.name}" if d.note in (5, 6, 8, 11, 12, 13) else row.name
            notes.setdefault(d.note, []).append(
                NoteRow(label, row.ledger_id, cur_map.get(key, (None, 0))[1], prev_map.get(key, (None, 0))[1])
            )

    for code in LINES:
        add(code, (cur_parts, prev_parts))
    notes.setdefault(4, []).append(NoteRow("Surplus in Statement of Profit and Loss for the year", None, cur_p["net"], prev_p["net"]))
    note_list = [Note(n, NOTE_TITLES[n], tuple(rows)) for n, rows in sorted(notes.items())]

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
    return Statements(
        balance_sheet=bs,
        profit_and_loss=pl,
        notes=note_list,
        regroupings=regroupings,
        footer=footer,
        previous_footer=prev_footer,
        has_previous=has_previous,
        balances=liab_c == assets_c,
        suspense_paise=suspense,
    )
