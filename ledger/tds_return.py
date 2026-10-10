"""The data a quarterly TDS return (Form 26Q, non-salary) is filed from.

Read from the same journal as ``ledger.tds``, so the return cannot disagree with the books: the deductee annexure is the
deductions (credits to ``TDS Payable``) in the quarter with the party they were made from, and the challan annexure is the
challans recorded for the quarter. Nothing is filed here -- this is the pack a person (or the return utility) takes the figures
from -- and the warnings are the things that cost money if missed:

* a deductee with no PAN (section 206AA: TDS at not less than 20%),
* a deposit later than its due date (interest at 1.5% a month or part of a month, from the deduction to the deposit),
* a return filed after its due date (section 234E fee of Rs 200 a day, never more than the TDS in the return).

Interest and fee are estimates to show what is at stake; the filed return and the challans are the authority.
Salary TDS (Form 24Q) is not here.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from ledger import tds
from ledger.models import Direction, JournalLine, TdsChallan

#: Month, day and calendar-year offset (from the financial year's start) of each quarter's return due date.
RETURN_DUE = {1: (7, 31, 0), 2: (10, 31, 0), 3: (1, 31, 1), 4: (5, 31, 1)}
INTEREST_PER_MONTH = 0.015
NO_PAN_MIN_RATE = 20.0
FEE_PER_DAY_PAISE = 200_00


class TdsReturnError(ValueError):
    """The pack cannot be built for what was asked."""


@dataclass
class Deductee:
    date: datetime.date
    party: str
    pan: str
    section: str
    paid_paise: int
    deducted_paise: int
    voucher: str

    @property
    def rate(self) -> float:
        return round(self.deducted_paise * 100 / self.paid_paise, 2) if self.paid_paise else 0.0


@dataclass
class Pack:
    financial_year: int
    quarter: int
    due: datetime.date
    deductees: list[Deductee] = field(default_factory=list)
    challans: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    interest_paise: int = 0
    fee_paise: int = 0

    @property
    def deducted_paise(self) -> int:
        return sum(d.deducted_paise for d in self.deductees)

    @property
    def deposited_paise(self) -> int:
        return sum(c["amount_paise"] for c in self.challans)


def return_due(year: int, quarter: int) -> datetime.date:
    month, day, offset = RETURN_DUE[quarter]
    return datetime.date(year + offset, month, day)


def pan_of(party) -> str:
    """The PAN, which is characters 3 to 12 of a GSTIN. Blank when the party has no GSTIN on file."""
    gstin = (party.gstin or "").strip().upper() if party is not None else ""
    return gstin[2:12] if len(gstin) == 15 else ""


def months_late(deducted: datetime.date, deposited: datetime.date) -> int:
    """Months or parts of a month from the deduction to the deposit, which is how the interest is counted."""
    months = (deposited.year - deducted.year) * 12 + (deposited.month - deducted.month)
    if months < 0:
        return 0
    return months + (1 if deposited.day > deducted.day else 0)


def _deposit_amount(challan, ledger) -> int:
    return sum(
        line.amount_paise
        for line in JournalLine.objects.filter(entry=challan.entry, ledger_account=ledger, direction=Direction.DEBIT)
    )


def build(client, year: int, quarter: int, *, today: datetime.date | None = None) -> Pack:
    if quarter not in RETURN_DUE:
        raise TdsReturnError("The quarter is 1 to 4 (April to June is 1).")
    today = today or datetime.date.today()
    pack = Pack(financial_year=year, quarter=quarter, due=return_due(year, quarter))
    ledger = tds.payable_ledger(client)
    if ledger is None:
        return pack

    def in_quarter(day: datetime.date) -> bool:
        return (day.year if day.month >= 4 else day.year - 1) == year and tds.quarter_of(day.month) == quarter

    credits = (
        JournalLine.objects.filter(firm_id=client.firm_id, ledger_account=ledger, direction=Direction.CREDIT)
        .select_related("entry", "entry__bill", "entry__bill__party")
        .order_by("entry__entry_date")
    )
    for line in credits:
        entry = line.entry
        if not in_quarter(entry.entry_date):
            continue
        bill = getattr(entry, "bill", None)
        party = bill.party if bill is not None else None
        pack.deductees.append(
            Deductee(
                date=entry.entry_date,
                party=party.canonical_name if party is not None else "(no party on the entry)",
                pan=pan_of(party),
                section=line.tds_section or tds.UNSPECIFIED,
                paid_paise=(bill.taxable_paise if bill is not None else 0) or 0,
                deducted_paise=line.amount_paise,
                voucher=f"{entry.get_voucher_type_display()} {entry.entry_no}",
            )
        )

    challans = list(TdsChallan.objects.filter(firm_id=client.firm_id, client=client).select_related("entry").order_by("paid_on"))
    sections = {d.section for d in pack.deductees}
    amounts = {c.pk: _deposit_amount(c, ledger) for c in challans}
    for challan in challans:
        if in_quarter(challan.paid_on) or challan.section in sections:
            pack.challans.append(
                {
                    "section": challan.section, "bsr_code": challan.bsr_code, "serial": challan.serial,
                    "paid_on": challan.paid_on, "amount_paise": amounts[challan.pk],
                }
            )

    _warn(pack, challans, amounts, today)
    return pack


def _warn(pack: Pack, challans, amounts: dict, today: datetime.date) -> None:
    for d in pack.deductees:
        if d.section == tds.UNSPECIFIED:
            pack.warnings.append(f"{d.voucher} ({d.party}): the deduction carries no section, so it cannot be reported.")
        if not d.pan and d.paid_paise and d.rate < NO_PAN_MIN_RATE:
            pack.warnings.append(
                f"{d.party} has no PAN on file and TDS was deducted at {d.rate:g}%. Section 206AA requires at least 20% "
                f"without a PAN."
            )
        elif not d.pan:
            pack.warnings.append(f"{d.party} has no PAN on file; the return needs one for every deductee.")

    # Deposits matched to deductions, oldest first within a section, to see which were late.
    deposits: dict[str, list[list]] = {}
    for challan in challans:
        deposits.setdefault(challan.section, []).append([challan.paid_on, amounts[challan.pk]])
    for d in sorted(pack.deductees, key=lambda x: x.date):
        due = tds.due_date(d.date.year, d.date.month)
        remaining = d.deducted_paise
        queue = deposits.get(d.section, [])
        while remaining > 0:
            slot = next((s for s in queue if s[1] > 0), None)
            if slot is None:
                if today > due:
                    interest = round(remaining * INTEREST_PER_MONTH * months_late(d.date, today))
                    pack.interest_paise += interest
                    pack.warnings.append(
                        f"{d.party} ({d.section}): {remaining / 100:,.2f} deducted on {d.date:%d-%m-%Y} is not deposited and was "
                        f"due by {due:%d-%m-%Y}; interest so far is about {interest / 100:,.2f}."
                    )
                break
            take = min(remaining, slot[1])
            slot[1] -= take
            remaining -= take
            if slot[0] > due:
                interest = round(take * INTEREST_PER_MONTH * months_late(d.date, slot[0]))
                pack.interest_paise += interest
                pack.warnings.append(
                    f"{d.party} ({d.section}): deposited {slot[0]:%d-%m-%Y}, after the due date {due:%d-%m-%Y}; interest is "
                    f"about {interest / 100:,.2f}."
                )
    if today > pack.due and pack.deductees:
        pack.fee_paise = min((today - pack.due).days * FEE_PER_DAY_PAISE, pack.deducted_paise)
        pack.warnings.append(
            f"The return was due on {pack.due:%d-%m-%Y}. If it is still not filed, the section 234E fee is about "
            f"{pack.fee_paise / 100:,.2f} so far (Rs 200 a day, up to the TDS in the return)."
        )


def workbook(client, pack: Pack) -> bytes:
    """The pack as an Excel file: a summary with the warnings, the deductee annexure and the challan annexure."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    from gst.report import _safe_cell

    bold = Font(bold=True)
    money = '#,##0.00;(#,##0.00);"-"'
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([_safe_cell(client.name)])
    ws.append([f"Form 26Q data, FY {pack.financial_year}-{(pack.financial_year + 1) % 100:02d} Q{pack.quarter}"])
    ws.append([f"Return due {pack.due:%d-%m-%Y}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(["TDS deducted", pack.deducted_paise / 100])
    ws.append(["TDS deposited (challans)", pack.deposited_paise / 100])
    ws.append(["Interest at stake (estimate)", pack.interest_paise / 100])
    ws.append(["Late filing fee at stake (estimate)", pack.fee_paise / 100])
    for row in ws.iter_rows(min_row=5, max_row=8, min_col=2, max_col=2):
        row[0].number_format = money
    ws.append([])
    ws.append(["Things to look at"])
    ws.cell(row=ws.max_row, column=1).font = bold
    for text in pack.warnings or ["Nothing found."]:
        ws.append([_safe_cell(text)])
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 18

    ded = wb.create_sheet("Deductees")
    ded.append(["Date", "Deductee", "PAN", "Section", "Amount paid or credited", "Rate %", "TDS deducted", "Voucher"])
    for cell in ded[1]:
        cell.font = bold
    for d in pack.deductees:
        ded.append([d.date, _safe_cell(d.party), d.pan or "PANNOTAVBL", d.section, d.paid_paise / 100, d.rate, d.deducted_paise / 100, d.voucher])
    for row in ded.iter_rows(min_row=2, min_col=1, max_col=1):
        row[0].number_format = "dd-mm-yyyy"
    for col in ("E", "G"):
        for cell in ded[col][1:]:
            cell.number_format = money

    chal = wb.create_sheet("Challans")
    chal.append(["Section", "BSR code", "Challan serial", "Date deposited", "Amount"])
    for cell in chal[1]:
        cell.font = bold
    for c in pack.challans:
        chal.append([c["section"], c["bsr_code"], c["serial"], c["paid_on"], c["amount_paise"] / 100])
    for row in chal.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].number_format = "dd-mm-yyyy"
    for cell in chal["E"][1:]:
        cell.number_format = money
    for sheet in (ded, chal):
        for letter in "ABCDEFGH":
            sheet.column_dimensions[letter].width = 22

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
