"""The working a month's PF (EPF ECR) and ESI contributions are filed from, taken from the booked salary run.

Per employee: the PF wages the contribution implies (the employee's 12% worked back), the employer's share split into pension (EPS,
8.33% of wages up to Rs 15,000) and provident fund (EPF, the rest), and the ESI figures with whether ESI applies (gross up to
Rs 21,000 a month). For the month: the employer's administration charge (0.5% of PF wages, at least Rs 500) and the EDLI contribution
(0.5% of PF wages up to Rs 15,000), and whether what the run credited to PF Payable and ESI Payable has been deposited by the 15th of
the next month. Things that would stop a return being filed are named: a missing UAN or ESIC number, ESI on someone above the limit,
ESI missing for someone below it, an employer share that is less than the pension share.

Interest and damages on a late deposit are not worked out. It writes nothing.
"""

from __future__ import annotations

import datetime

from classify.models import LedgerAccount
from ledger.models import Direction, JournalLine, PayrollRun

PF_WAGE_CEILING = 15_000_00
ESI_WAGE_LIMIT = 21_000_00
EPS_BP = 833  # 8.33%, in hundredths of a percent
ADMIN_BP = 50  # 0.5%
EDLI_BP = 50
ADMIN_MINIMUM = 500_00
ESI_EMPLOYEE_BP = 75  # 0.75%


def _bp(amount: int, bp: int) -> int:
    return round(amount * bp / 10_000)


def due_date(year: int, month: int) -> datetime.date:
    return datetime.date(year + (month == 12), month % 12 + 1, 15)


def _deposits(client, name: str, year: int, month: int, today: datetime.date) -> dict:
    ledger = LedgerAccount.objects.filter(firm_id=client.firm_id, client=client, name=name).first()
    if ledger is None:
        return {"credited_paise": 0, "deposited_on_time_paise": 0, "deposited_late_paise": 0, "balance_paise": 0}
    start = datetime.date(year, month, 1)
    due = due_date(year, month)
    lines = list(JournalLine.objects.filter(firm_id=client.firm_id, ledger_account=ledger).select_related("entry"))
    credited = sum(
        line.amount_paise for line in lines
        if line.direction == Direction.CREDIT and line.entry.entry_date.year == year and line.entry.entry_date.month == month
    )
    after = [line for line in lines if line.direction == Direction.DEBIT and line.entry.entry_date >= start]
    return {
        "credited_paise": credited,
        "deposited_on_time_paise": sum(line.amount_paise for line in after if line.entry.entry_date <= due),
        "deposited_late_paise": sum(line.amount_paise for line in after if line.entry.entry_date > due),
        "balance_paise": sum(
            (1 if line.direction == Direction.CREDIT else -1) * line.amount_paise for line in lines if line.entry.entry_date <= today
        ),
    }


def build(client, year: int, month: int, *, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    run = PayrollRun.objects.filter(firm_id=client.firm_id, client=client, year=year, month=month).first()
    due = due_date(year, month)
    if run is None:
        return {"year": year, "month": month, "has_run": False, "due": due.isoformat()}

    rows, warnings = [], []
    totals = {
        "pf_wages_paise": 0, "edli_wages_paise": 0, "pf_employee_paise": 0, "pf_employer_paise": 0, "eps_paise": 0, "epf_paise": 0,
        "esi_wages_paise": 0, "esi_employee_paise": 0, "esi_employer_paise": 0,
    }
    for line in run.lines.select_related("employee").order_by("employee__name"):
        e = line.employee
        wages = round(line.pf_employee_paise * 100 / 12) if line.pf_employee_paise else 0
        eps = _bp(min(wages, PF_WAGE_CEILING), EPS_BP) if line.pf_employer_paise else 0
        epf = line.pf_employer_paise - eps
        esi_applies = line.gross_paise <= ESI_WAGE_LIMIT
        has_esi = bool(line.esi_employee_paise or line.esi_employer_paise)
        rows.append(
            {
                "employee": e.name, "uan": e.uan, "esic_number": e.esic_number, "gross_paise": line.gross_paise,
                "pf_wages_paise": wages, "pf_employee_paise": line.pf_employee_paise, "pf_employer_paise": line.pf_employer_paise,
                "eps_paise": eps, "epf_paise": epf, "esi_applies": esi_applies,
                "esi_employee_paise": line.esi_employee_paise, "esi_employer_paise": line.esi_employer_paise,
            }
        )
        if line.pf_employee_paise or line.pf_employer_paise:
            if not e.uan:
                warnings.append(f"{e.name}: no UAN on file, so the ECR cannot name them.")
            if epf < 0:
                warnings.append(f"{e.name}: the employer's PF is less than the pension share on the same wages; check the figures.")
        if has_esi and not e.esic_number:
            warnings.append(f"{e.name}: no ESIC number on file.")
        if not esi_applies and has_esi:
            warnings.append(f"{e.name}: gross is over the ESI limit but ESI was deducted.")
        if esi_applies and not has_esi and line.gross_paise:
            warnings.append(f"{e.name}: gross is within the ESI limit but no ESI was deducted.")
        if esi_applies and line.esi_employee_paise and abs(line.esi_employee_paise - _bp(line.gross_paise, ESI_EMPLOYEE_BP)) > 100:
            warnings.append(f"{e.name}: the employee's ESI is not 0.75% of gross.")
        totals["pf_wages_paise"] += wages
        totals["edli_wages_paise"] += min(wages, PF_WAGE_CEILING)
        totals["pf_employee_paise"] += line.pf_employee_paise
        totals["pf_employer_paise"] += line.pf_employer_paise
        totals["eps_paise"] += eps
        totals["epf_paise"] += epf
        if has_esi:
            totals["esi_wages_paise"] += line.gross_paise
        totals["esi_employee_paise"] += line.esi_employee_paise
        totals["esi_employer_paise"] += line.esi_employer_paise

    pf_total = totals["pf_employee_paise"] + totals["pf_employer_paise"]
    esi_total = totals["esi_employee_paise"] + totals["esi_employer_paise"]
    admin = max(_bp(totals["pf_wages_paise"], ADMIN_BP), ADMIN_MINIMUM) if pf_total else 0
    edli = _bp(totals["edli_wages_paise"], EDLI_BP)
    pf_dep = _deposits(client, "PF Payable", year, month, today)
    esi_dep = _deposits(client, "ESI Payable", year, month, today)
    for label, total, dep in (("PF", pf_total, pf_dep), ("ESI", esi_total, esi_dep)):
        paid = dep["deposited_on_time_paise"] + dep["deposited_late_paise"]
        if total and paid < total and today > due:
            warnings.append(
                f"{label} of {total / 100:,.2f} for this month was due by {due:%d-%m-%Y}; only {paid / 100:,.2f} has been deposited. "
                "Interest and damages are not worked out here."
            )
        elif total and dep["deposited_late_paise"]:
            warnings.append(f"Some {label} was deposited after {due:%d-%m-%Y}; interest and damages may apply.")
    return {
        "year": year, "month": month, "has_run": True, "due": due.isoformat(), "rows": rows, "totals": totals,
        "pf_total_paise": pf_total, "admin_charge_paise": admin, "edli_paise": edli, "esi_total_paise": esi_total,
        "pf_deposit": pf_dep, "esi_deposit": esi_dep, "warnings": warnings,
    }
