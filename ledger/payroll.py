"""Salaries: each employee's account, and a month's run booked as one journal entry.

The figures come from the salary sheet and are typed, not computed: the books record what was decided, they do not decide
PF or ESI. One run is one balanced entry:

    Dr Salaries                     gross, all employees
    Dr Employer PF Contribution     the employer's share
    Dr Employer ESI Contribution    the employer's share
        Cr PF Payable               employee and employer shares
        Cr ESI Payable              employee and employer shares
        Cr TDS Payable              tax deducted on salary, carrying section 192 so the TDS page counts it
        Cr Salary Payable - <name>  each employee's net

The payment to the employee, and the deposits of PF, ESI and TDS, are bank entries a person places on those accounts as
usual. An employee's account is opened on their first run and is kept out of what the model is shown.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from classify.models import LedgerAccount, LedgerGroup
from core.access import require_posting_rights
from core.rbac import require_permission
from ledger import approval, billing, editing
from ledger.models import (
    ChangeAction,
    Direction,
    Employee,
    EntryKind,
    JournalEntry,
    JournalLine,
    PayrollLine,
    PayrollRun,
    VoucherType,
)

SALARY_TDS_SECTION = "192"


class PayrollError(ValueError):
    """The run cannot be booked. The message says what to change."""


@dataclass(frozen=True)
class SalaryInput:
    employee: Employee
    gross_paise: int
    pf_employee_paise: int = 0
    pf_employer_paise: int = 0
    esi_employee_paise: int = 0
    esi_employer_paise: int = 0
    tds_paise: int = 0
    other_deduction_paise: int = 0

    @property
    def deductions_paise(self) -> int:
        return self.pf_employee_paise + self.esi_employee_paise + self.tds_paise + self.other_deduction_paise

    @property
    def net_paise(self) -> int:
        return self.gross_paise - self.deductions_paise


@transaction.atomic
def add_employee(client, name: str, *, membership) -> Employee:
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    name = " ".join((name or "").split())
    if not name:
        raise PayrollError("Give the employee a name.")
    if Employee.objects.filter(firm_id=client.firm_id, client=client, name__iexact=name).exists():
        raise PayrollError(f"{name} is already an employee of this client.")
    return Employee.objects.create(firm_id=client.firm_id, client=client, name=name[:200])


def _account(employee: Employee) -> LedgerAccount:
    """The employee's own account, opened the first time they are paid a salary."""
    if employee.ledger_id:
        return employee.ledger
    ledger_name = f"Salary Payable - {employee.name}"
    ledger, created = LedgerAccount.objects.get_or_create(
        firm_id=employee.firm_id, client_id=employee.client_id, name=ledger_name, defaults={"group": LedgerGroup.CURRENT_LIABILITY}
    )
    if not created and Employee.objects.filter(ledger=ledger).exists():
        raise PayrollError(f"A ledger called {ledger_name!r} already belongs to another employee. Rename one of them.")
    employee.ledger = ledger
    employee.save(update_fields=["ledger"])
    return ledger


def _check(item: SalaryInput) -> None:
    values = (
        item.gross_paise, item.pf_employee_paise, item.pf_employer_paise, item.esi_employee_paise,
        item.esi_employer_paise, item.tds_paise, item.other_deduction_paise,
    )
    if any(v < 0 for v in values):
        raise PayrollError(f"{item.employee.name}: amounts cannot be negative.")
    if item.gross_paise <= 0:
        raise PayrollError(f"{item.employee.name}: the gross salary must be more than zero.")
    if item.net_paise < 0:
        raise PayrollError(f"{item.employee.name}: the deductions are more than the gross salary.")


@transaction.atomic
def post_run(client, year: int, month: int, items: list[SalaryInput], *, membership) -> PayrollRun:
    """Book the month's salaries as one entry dated the last day of the month. Once per month."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, client)
    if not 1 <= month <= 12:
        raise PayrollError("The month must be 1 to 12.")
    if not items:
        raise PayrollError("Add at least one employee to the run.")
    if len({i.employee.pk for i in items}) != len(items):
        raise PayrollError("An employee is listed twice.")
    for item in items:
        if item.employee.client_id != client.pk or item.employee.firm_id != client.firm_id:
            raise PayrollError("An employee belongs to a different client.")
        _check(item)
    if PayrollRun.objects.filter(firm_id=client.firm_id, client=client, year=year, month=month).exists():
        raise PayrollError(f"Salaries for {datetime.date(year, month, 1):%B %Y} are already booked.")

    last = (datetime.date(year + (month == 12), month % 12 + 1, 1)) - datetime.timedelta(days=1)
    through = editing.locked_through(client.pk)
    if through is not None and last <= through:
        raise PayrollError(f"The books are sealed through {through:%d-%m-%Y}, so salaries dated {last:%d-%m-%Y} cannot be booked.")

    fy = year if month >= 4 else year - 1
    total = lambda attr: sum(getattr(i, attr) for i in items)  # noqa: E731
    gross = total("gross_paise")
    pf = total("pf_employee_paise") + total("pf_employer_paise")
    esi = total("esi_employee_paise") + total("esi_employer_paise")
    tds = total("tds_paise")
    other = total("other_deduction_paise")

    salaries = billing.standard_ledger(client, "Salaries")
    employer_pf = billing.standard_ledger(client, "Employer PF Contribution")
    employer_esi = billing.standard_ledger(client, "Employer ESI Contribution")
    pf_payable = billing.standard_ledger(client, "PF Payable")
    esi_payable = billing.standard_ledger(client, "ESI Payable")
    tds_payable = billing.standard_ledger(client, billing.TDS_PAYABLE)

    entry = JournalEntry.objects.create(
        firm_id=client.firm_id,
        client=client,
        entry_no=approval.allocate_voucher_number(client, fy, VoucherType.JOURNAL),
        financial_year=fy,
        entry_date=last,
        voucher_type=VoucherType.JOURNAL,
        entry_kind=EntryKind.VOUCHER,
        narration=f"Being salaries for {datetime.date(year, month, 1):%B %Y}",
        approved_by=membership.user,
        approved_at=timezone.now(),
    )
    lines = [JournalLine.build(entry=entry, ledger_account=salaries, direction=Direction.DEBIT, amount_paise=gross)]
    for ledger, amount in ((employer_pf, total("pf_employer_paise")), (employer_esi, total("esi_employer_paise"))):
        if amount:
            lines.append(JournalLine.build(entry=entry, ledger_account=ledger, direction=Direction.DEBIT, amount_paise=amount))
    for ledger, amount in ((pf_payable, pf), (esi_payable, esi)):
        if amount:
            lines.append(JournalLine.build(entry=entry, ledger_account=ledger, direction=Direction.CREDIT, amount_paise=amount))
    if tds:
        lines.append(
            JournalLine.build(
                entry=entry, ledger_account=tds_payable, direction=Direction.CREDIT, amount_paise=tds, tds_section=SALARY_TDS_SECTION
            )
        )
    if other:
        other_ledger = billing.standard_ledger(client, "Other Payables")
        lines.append(JournalLine.build(entry=entry, ledger_account=other_ledger, direction=Direction.CREDIT, amount_paise=other))
    for item in items:
        if item.net_paise:
            lines.append(
                JournalLine.build(entry=entry, ledger_account=_account(item.employee), direction=Direction.CREDIT, amount_paise=item.net_paise)
            )
    JournalLine.objects.bulk_create(lines)

    run = PayrollRun.objects.create(
        firm_id=client.firm_id, client=client, year=year, month=month, entry=entry, gross_paise=gross, net_paise=total("net_paise")
    )
    PayrollLine.objects.bulk_create(
        [
            PayrollLine(
                firm_id=client.firm_id, run=run, employee=i.employee, gross_paise=i.gross_paise,
                pf_employee_paise=i.pf_employee_paise, pf_employer_paise=i.pf_employer_paise,
                esi_employee_paise=i.esi_employee_paise, esi_employer_paise=i.esi_employer_paise, tds_paise=i.tds_paise,
                other_deduction_paise=i.other_deduction_paise, net_paise=i.net_paise,
            )
            for i in items
        ]
    )
    return run


@transaction.atomic
def remove_run(run: PayrollRun, *, membership, note: str = "") -> None:
    """Take a month's salaries out of the books (before they are sealed). The change log keeps what the entry was."""
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, run.client)
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    entry = JournalEntry.objects.select_for_update().get(pk=run.entry_id)
    editing.require_editable(entry)
    editing.record_change(entry, ChangeAction.REMOVED, actor=membership.user, before=editing.snapshot(entry), note=note or "Payroll run removed")
    run.delete()
    entry.lines.all().delete()
    entry.delete()
