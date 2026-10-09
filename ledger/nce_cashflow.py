"""The Cash Flow Statement, by the indirect method, for a Large non-corporate entity.

Built from the two year-end positions and the year's profit, never from the bank rows, so it can only disagree with the balance
sheet by something the books themselves contain. Whatever is left unexplained is shown as one visible line and warned about,
the way a rounding difference is, never buried.

The order is the one the accounting standard sets:

* **A. Operating activities.** Profit before tax (after partners' remuneration, as the statement of profit and loss shows it),
  with depreciation and finance costs added back and interest income taken out (they belong to the other two sections), then the
  change in each working-capital line, then the current tax charge. Tax is taken out as the year's charge because the movements in
  tax payable and advance tax already sit in the working-capital lines, which together leave exactly the tax paid.
* **B. Investing activities.** Purchase of fixed assets (the change in their net book value plus the year's depreciation, so
  sales are netted in), purchase of investments, interest received.
* **C. Financing activities.** Borrowings taken or repaid, capital introduced or withdrawn (the change in owners' funds other than
  the year's profit), finance costs paid.

Then net change, opening and closing cash and bank balances. A change in deferred tax assets or liabilities is not cash: it is
equal and opposite to the deferred tax charge in the books, and any difference shows up in the reconciling line.

This module is arithmetic only: it has no database and no knowledge of ledgers. ``ledger.nce`` feeds it each year's line totals
(assets and expenses positive as debits, liabilities, equity and income positive as credits) and assembles the rows.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The balance-sheet lines whose change is a movement in fixed assets.
_FIXED = ("NCA.PPE", "NCA.INTANG", "NCA.CWIP", "NCA.IAUD")
_INVESTMENTS = ("NCA.INV", "CA.INV")


@dataclass(frozen=True)
class CashRow:
    key: str
    label: str
    #: ``heading``, ``line``, ``subtotal`` or ``total``.
    kind: str
    level: int
    paise: int | None = None


@dataclass(frozen=True)
class CashFlow:
    rows: tuple[CashRow, ...]
    operating_paise: int
    investing_paise: int
    financing_paise: int
    opening_paise: int
    closing_paise: int
    #: What the closing balance differs from opening plus the three sections by. Zero when the books agree with themselves.
    unexplained_paise: int


def _change(cur: dict, prev: dict, *codes: str) -> int:
    return sum(cur.get(c, 0) - prev.get(c, 0) for c in codes)


def cash_flow(
    cur: dict,
    prev: dict,
    *,
    profit_before_tax: int,
    net_profit: int,
    interest_income: int,
    owners_funds_cur: int,
    owners_funds_prev: int,
    show_difference: bool = False,
) -> CashFlow:
    """One year's statement from this year's and last year's line totals (an empty dict stands for "no books", all nil)."""
    depreciation = cur.get("PL.DEP", 0)
    finance = cur.get("PL.FIN", 0)
    tax = cur.get("PL.TAXC", 0)

    operating_profit = profit_before_tax + depreciation + finance - interest_income
    inventories = -_change(cur, prev, "CA.STOCK")
    receivables = -_change(cur, prev, "CA.REC")
    advances = -_change(cur, prev, "CA.LOANS", "NCA.LOANS")
    other_assets = -_change(cur, prev, "CA.OTH", "NCA.OTH")
    payables = _change(cur, prev, "CL.PAY")
    other_liabilities = _change(cur, prev, "CL.OTH", "NCL.OTH")
    provisions = _change(cur, prev, "CL.PROV", "NCL.PROV")
    working = inventories + receivables + advances + other_assets + payables + other_liabilities + provisions
    generated = operating_profit + working
    operating = generated - tax

    fixed = -(_change(cur, prev, *_FIXED) + depreciation)
    investments = -_change(cur, prev, *_INVESTMENTS)
    investing = fixed + investments + interest_income

    borrowings = _change(cur, prev, "NCL.BORR", "CL.BORR")
    owners = (owners_funds_cur - owners_funds_prev) - net_profit
    financing = borrowings + owners - finance

    opening, closing = prev.get("CA.CASH", 0), cur.get("CA.CASH", 0)
    net = operating + investing + financing
    unexplained = closing - opening - net

    def row(key, label, paise, level=2, kind="line"):
        return CashRow(key, label, kind, level, paise)

    def head(key, label, level=0):
        return CashRow(key, label, "heading", level)

    rows = [
        head("A", "A. Cash flow from operating activities"),
        row("A.pbt", "Net profit before tax", profit_before_tax),
        head("A.adj", "Adjustments for:", 1),
        row("A.dep", "Depreciation and amortization expense", depreciation),
        row("A.fin", "Finance costs", finance),
        row("A.int", "Interest income (shown under investing activities)", -interest_income),
        row("A.op", "Operating profit before working capital changes", operating_profit, 1, "subtotal"),
        head("A.wc", "Adjustments for changes in working capital:", 1),
        row("A.inv", "(Increase)/decrease in inventories", inventories),
        row("A.rec", "(Increase)/decrease in trade receivables", receivables),
        row("A.adv", "(Increase)/decrease in loans and advances", advances),
        row("A.oa", "(Increase)/decrease in other assets", other_assets),
        row("A.pay", "Increase/(decrease) in trade payables", payables),
        row("A.ol", "Increase/(decrease) in other liabilities", other_liabilities),
        row("A.prov", "Increase/(decrease) in provisions", provisions),
        row("A.gen", "Cash generated from operations", generated, 1, "subtotal"),
        row("A.tax", "Direct taxes paid (net of refunds)", -tax),
        row("A.net", "Net cash flow from operating activities (A)", operating, 0, "total"),
        head("B", "B. Cash flow from investing activities"),
        row("B.fa", "Purchase of fixed assets, net of sales", fixed),
        row("B.inv", "Purchase of investments, net of sales", investments),
        row("B.int", "Interest received", interest_income),
        row("B.net", "Net cash flow from/(used in) investing activities (B)", investing, 0, "total"),
        head("C", "C. Cash flow from financing activities"),
        row("C.bor", "Proceeds from/(repayment of) borrowings", borrowings),
        row("C.cap", "Capital introduced/(withdrawn), net of drawings", owners),
        row("C.fin", "Finance costs paid", -finance),
        row("C.net", "Net cash flow from/(used in) financing activities (C)", financing, 0, "total"),
        row("N", "Net increase/(decrease) in cash and cash equivalents (A + B + C)", net, 0, "total"),
        *([row("N.diff", "Difference the books do not explain", unexplained, 1)] if unexplained or show_difference else []),
        row("N.open", "Cash and cash equivalents at the beginning of the year", opening, 1),
        row("N.close", "Cash and cash equivalents at the end of the year", closing, 0, "total"),
    ]
    return CashFlow(tuple(rows), operating, investing, financing, opening, closing, unexplained)
