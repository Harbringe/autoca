"""The data a quarterly salary TDS return (Form 24Q) is filed from: who was paid what, what was deducted under section 192, and
the challans that deposited it. Read from the payroll runs and challans in the books.

An employee's PAN is not stored (the register holds no personal identifiers for staff), so every employee is listed without
one and the pack says so: the return utility needs it for each, and the filer adds it there.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from ledger import tds, tds_return
from ledger.models import Direction, JournalLine, PayrollLine, TdsChallan

SECTION = "192"


@dataclass
class Row:
    employee: str
    gross_paise: int = 0
    tds_paise: int = 0


@dataclass
class SalaryPack:
    financial_year: int
    quarter: int
    due: datetime.date
    rows: list[Row] = field(default_factory=list)
    challans: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    interest_paise: int = 0
    fee_paise: int = 0

    @property
    def deducted_paise(self) -> int:
        return sum(r.tds_paise for r in self.rows)

    @property
    def deposited_paise(self) -> int:
        return sum(c["amount_paise"] for c in self.challans)


def build(client, year: int, quarter: int, *, today: datetime.date | None = None) -> SalaryPack:
    if quarter not in tds_return.RETURN_DUE:
        raise tds_return.TdsReturnError("The quarter is 1 to 4 (April to June is 1).")
    today = today or datetime.date.today()
    pack = SalaryPack(financial_year=year, quarter=quarter, due=tds_return.return_due(year, quarter))

    def in_quarter(y: int, m: int) -> bool:
        return (y if m >= 4 else y - 1) == year and tds.quarter_of(m) == quarter

    by_employee: dict[str, Row] = {}
    monthly: dict[tuple, int] = {}
    lines = PayrollLine.objects.filter(firm_id=client.firm_id, run__client=client).select_related("run", "employee")
    for line in lines:
        if not in_quarter(line.run.year, line.run.month):
            continue
        row = by_employee.setdefault(line.employee.name, Row(line.employee.name))
        row.gross_paise += line.gross_paise
        row.tds_paise += line.tds_paise
        key = (line.run.year, line.run.month)
        monthly[key] = monthly.get(key, 0) + line.tds_paise
    pack.rows = sorted(by_employee.values(), key=lambda r: r.employee.lower())

    ledger = tds.payable_ledger(client)
    deposits: list[list] = []
    for challan in TdsChallan.objects.filter(firm_id=client.firm_id, client=client, section=SECTION).select_related("entry"):
        amount = 0
        if ledger is not None:
            amount = sum(
                line.amount_paise
                for line in JournalLine.objects.filter(entry=challan.entry, ledger_account=ledger, direction=Direction.DEBIT)
            )
        pack.challans.append(
            {"section": SECTION, "bsr_code": challan.bsr_code, "serial": challan.serial, "paid_on": challan.paid_on, "amount_paise": amount}
        )
        deposits.append([challan.paid_on, amount])

    if pack.rows:
        pack.warnings.append(
            "PAN is not held for employees here; add each employee's PAN in the return utility. A return without it is rejected."
        )
    for (y, m), deducted in sorted(monthly.items()):
        if deducted <= 0:
            continue
        due = tds.due_date(y, m)
        on = datetime.date(y, m, 1)
        remaining = deducted
        while remaining > 0:
            slot = next((d for d in deposits if d[1] > 0), None)
            if slot is None:
                if today > due:
                    interest = round(remaining * tds_return.INTEREST_PER_MONTH * tds_return.months_late(on, today))
                    pack.interest_paise += interest
                    pack.warnings.append(
                        f"{m:02d}/{y}: {remaining / 100:,.2f} of salary TDS is not deposited and was due by {due:%d-%m-%Y}; "
                        f"interest so far is about {interest / 100:,.2f}."
                    )
                break
            take = min(remaining, slot[1])
            slot[1] -= take
            remaining -= take
            if slot[0] > due:
                interest = round(take * tds_return.INTEREST_PER_MONTH * tds_return.months_late(on, slot[0]))
                pack.interest_paise += interest
                pack.warnings.append(
                    f"{m:02d}/{y}: deposited {slot[0]:%d-%m-%Y}, after the due date {due:%d-%m-%Y}; "
                    f"interest is about {interest / 100:,.2f}."
                )
    if today > pack.due and pack.rows:
        pack.fee_paise = min((today - pack.due).days * tds_return.FEE_PER_DAY_PAISE, pack.deducted_paise)
        pack.warnings.append(
            f"The return was due on {pack.due:%d-%m-%Y}. If it is still not filed, the section 234E fee is about "
            f"{pack.fee_paise / 100:,.2f} so far."
        )
    return pack


def workbook(client, pack: SalaryPack) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from gst.report import _safe_cell

    money = '#,##0.00;(#,##0.00);"-"'
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([_safe_cell(client.name)])
    ws.append([f"Form 24Q data, FY {pack.financial_year}-{(pack.financial_year + 1) % 100:02d} Q{pack.quarter}"])
    ws.append([f"Return due {pack.due:%d-%m-%Y}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["TDS deducted", pack.deducted_paise / 100])
    ws.append(["TDS deposited (challans)", pack.deposited_paise / 100])
    ws.append(["Interest at stake (estimate)", pack.interest_paise / 100])
    ws.append(["Late filing fee at stake (estimate)", pack.fee_paise / 100])
    ws.append([])
    ws.append(["Things to look at"])
    for text in pack.warnings or ["Nothing found."]:
        ws.append([_safe_cell(text)])
    ws.column_dimensions["A"].width = 60
    emp = wb.create_sheet("Employees")
    emp.append(["Employee", "PAN", "Gross salary", "TDS deducted"])
    for r in pack.rows:
        emp.append([_safe_cell(r.employee), "PANNOTAVBL", r.gross_paise / 100, r.tds_paise / 100])
    for col in ("C", "D"):
        for cell in emp[col][1:]:
            cell.number_format = money
    chal = wb.create_sheet("Challans")
    chal.append(["BSR code", "Challan serial", "Date deposited", "Amount"])
    for c in pack.challans:
        chal.append([_safe_cell(c["bsr_code"]), _safe_cell(c["serial"]), c["paid_on"], c["amount_paise"] / 100])
    for row in chal.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].number_format = "dd-mm-yyyy"
    for sheet in (emp, chal):
        for letter in "ABCD":
            sheet.column_dimensions[letter].width = 24
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
