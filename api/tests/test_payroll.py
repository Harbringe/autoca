"""A month of salaries is one balanced journal entry, with each employee's net on an account of their own."""

from __future__ import annotations

import datetime

import pytest

from api.tests.conftest import sign_in
from api.tests.test_bills import base
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def add(api, client_record, name):
    response = api.post(f"{base(client_record)}/employees/", {"name": name}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def line(employee, **over):
    body = {
        "employee": employee["id"], "gross_paise": 50_000_00, "pf_employee_paise": 6_000_00, "pf_employer_paise": 6_000_00,
        "esi_employee_paise": 0, "esi_employer_paise": 0, "tds_paise": 2_000_00, "other_deduction_paise": 0, **over,
    }
    return body


def run(api, client_record, lines, year=2025, month=5):
    return api.post(f"{base(client_record)}/payroll/", {"year": year, "month": month, "lines": lines}, format="json")


def entry_lines(entry_id):
    entry = JournalEntry.objects.get(pk=entry_id)
    return sorted((ln.ledger_account.name, ln.direction, ln.amount_paise, ln.tds_section) for ln in entry.lines.select_related("ledger_account"))


def test_a_run_books_one_balanced_entry_with_each_employees_net_on_their_own_account(api, client_record):
    asha = add(api, client_record, "Asha Nair")
    ravi = add(api, client_record, "Ravi Kumar")

    response = run(api, client_record, [line(asha), line(ravi, gross_paise=30_000_00, pf_employee_paise=3_600_00, pf_employer_paise=3_600_00, tds_paise=0)])

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["gross_paise"] == 80_000_00 and body["net_paise"] == (50_000_00 - 8_000_00) + (30_000_00 - 3_600_00)
    rows = entry_lines(body["entry"])
    assert ("Salaries", "DR", 80_000_00, "") in rows
    assert ("Employer PF Contribution", "DR", 9_600_00, "") in rows
    assert ("PF Payable", "CR", 9_600_00 + 9_600_00, "") in rows
    assert ("TDS Payable", "CR", 2_000_00, "192") in rows
    assert ("Salary Payable - Asha Nair", "CR", 42_000_00, "") in rows
    assert ("Salary Payable - Ravi Kumar", "CR", 26_400_00, "") in rows
    entry = JournalEntry.objects.get(pk=body["entry"])
    assert entry.entry_date == datetime.date(2025, 5, 31)
    assert sum(ln.signed_paise for ln in entry.lines.all()) == 0


def test_the_tds_on_salary_shows_on_the_tds_page_under_section_192(api, client_record):
    asha = add(api, client_record, "Asha Nair")
    run(api, client_record, [line(asha)])

    months = api.get(f"{base(client_record)}/tds/summary/").json()["months"]

    assert [(m["section"], m["deducted_paise"]) for m in months] == [("192", 2_000_00)]


def test_a_month_is_booked_once(api, client_record):
    asha = add(api, client_record, "Asha Nair")
    run(api, client_record, [line(asha)])

    again = run(api, client_record, [line(asha)])

    assert again.status_code == 422 and "already booked" in again.json()["detail"]


def test_deductions_above_the_gross_are_refused_and_nothing_is_booked(api, client_record):
    asha = add(api, client_record, "Asha Nair")

    refused = run(api, client_record, [line(asha, gross_paise=5_000_00)])

    assert refused.status_code == 422 and "more than the gross" in refused.json()["detail"]
    assert api.get(f"{base(client_record)}/payroll/").json()["results"] == []


def test_an_employee_is_not_added_twice(api, client_record):
    add(api, client_record, "Asha Nair")

    again = api.post(f"{base(client_record)}/employees/", {"name": "asha nair"}, format="json")

    assert again.status_code == 422 and "already an employee" in again.json()["detail"]


def test_a_run_can_be_taken_out_before_sealing_and_booked_again(api, client_record):
    asha = add(api, client_record, "Asha Nair")
    made = run(api, client_record, [line(asha)]).json()

    gone = api.post(f"{base(client_record)}/payroll/{made['id']}/remove/", {}, format="json")

    assert gone.status_code == 204
    assert run(api, client_record, [line(asha, gross_paise=60_000_00)]).status_code == 201


def test_sealed_books_refuse_salaries_dated_inside_them(api, client_record):
    asha = add(api, client_record, "Asha Nair")
    type(client_record).objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 6, 30))

    refused = run(api, client_record, [line(asha)])

    assert refused.status_code == 422 and "sealed through" in refused.json()["detail"]


def test_an_employee_of_another_client_is_not_found(api, client_record, firm):
    import datetime as dt

    from core.provisioning import create_client

    other = create_client(firm, "Other Client", dt.date(2025, 4, 1))
    stranger = add(api, other, "Someone Else")

    refused = run(api, client_record, [line(stranger)])

    assert refused.status_code == 400 and "Not employees of this client" in str(refused.json())


def test_a_read_only_member_may_look_but_not_book(api, client_record, reader):
    asha = add(api, client_record, "Asha Nair")
    viewer = sign_in(reader.user)

    assert viewer.get(f"{base(client_record)}/payroll/").status_code == 200
    assert run(viewer, client_record, [line(asha)]).status_code == 403


def test_the_model_is_never_shown_an_employees_ledger(api, client_record):
    from classify.models import LedgerAccount

    asha = add(api, client_record, "Asha Nair")
    run(api, client_record, [line(asha)])

    ledger = LedgerAccount.objects.get(client=client_record, name="Salary Payable - Asha Nair")

    assert hasattr(ledger, "employee_record")
