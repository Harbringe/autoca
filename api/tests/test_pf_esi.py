"""The PF and ESI working for a month: pension and provident-fund split, admin and EDLI, ESI, missing numbers, deposits."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base
from api.tests.test_payroll import add, line, run

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def working(api, client, year=2025, month=5):
    done = api.get(f"{base(client)}/payroll/pf-esi/", {"year": year, "month": month})
    assert done.status_code == 200, done.content
    return done.json()


@pytest.fixture
def booked(api, client_record):
    asha = add(api, client_record, "Asha")
    bhanu = add(api, client_record, "Bhanu")
    made = run(
        api, client_record,
        [
            line(asha, gross_paise=12_000_00, pf_employee_paise=1_440_00, pf_employer_paise=1_440_00, esi_employee_paise=90_00, esi_employer_paise=390_00, tds_paise=0),
            line(bhanu, gross_paise=50_000_00, pf_employee_paise=1_800_00, pf_employer_paise=1_800_00, tds_paise=0),
        ],
    )
    assert made.status_code == 201, made.content
    return asha, bhanu


def test_a_month_with_no_salary_run_says_so(api, client_record):
    body = working(api, client_record)
    assert body["has_run"] is False and body["due"] == "2025-06-15"


def test_the_employers_pf_is_split_into_pension_and_provident_fund_with_admin_and_edli(api, client_record, booked):
    body = working(api, client_record)
    asha, bhanu = body["rows"]
    assert (asha["employee"], asha["pf_wages_paise"], asha["eps_paise"], asha["epf_paise"]) == ("Asha", 12_000_00, 99_960, 44_040)
    assert (bhanu["pf_wages_paise"], bhanu["eps_paise"], bhanu["epf_paise"]) == (15_000_00, 124_950, 55_050)
    assert body["pf_total_paise"] == 1_440_00 * 2 + 1_800_00 * 2
    assert body["admin_charge_paise"] == 500_00, "0.5% of the wages is under the Rs 500 minimum"
    assert body["edli_paise"] == 13_500
    assert asha["esi_applies"] is True and bhanu["esi_applies"] is False


def test_missing_numbers_and_an_unpaid_deposit_are_named_and_a_uan_clears_its_warning(api, client_record, booked):
    asha, bhanu = booked
    warnings = working(api, client_record)["warnings"]
    assert any("Asha: no UAN" in w for w in warnings) and any("Bhanu: no UAN" in w for w in warnings) and any("Asha: no ESIC" in w for w in warnings)
    assert any(w.startswith("PF of") and "due by 15-06-2025" in w for w in warnings)
    done = api.patch(f"{base(client_record)}/employees/{bhanu['id']}/", {"uan": "100200300400"}, format="json")
    assert done.status_code == 200 and done.json()["uan"] == "100200300400"
    assert not any("Bhanu: no UAN" in w for w in working(api, client_record)["warnings"])


def test_esi_on_someone_above_the_limit_is_named(api, client_record):
    cara = add(api, client_record, "Cara")
    run(api, client_record, [line(cara, gross_paise=30_000_00, pf_employee_paise=1_800_00, pf_employer_paise=1_800_00, esi_employee_paise=225_00, esi_employer_paise=975_00, tds_paise=0)])
    assert any("Cara: gross is over the ESI limit" in w for w in working(api, client_record)["warnings"])


def test_a_bad_uan_or_esic_number_and_a_bad_month_are_refused(api, client_record, booked):
    asha, _ = booked
    url = f"{base(client_record)}/employees/{asha['id']}/"
    assert api.patch(url, {"uan": "123"}, format="json").status_code == 400
    assert api.patch(url, {"esic_number": "12345"}, format="json").status_code == 400
    assert api.patch(url, {"name": "Someone else"}, format="json").status_code == 400
    assert api.get(f"{base(client_record)}/payroll/pf-esi/", {"year": 2025, "month": 13}).status_code == 400


def test_wages_entered_on_the_salary_line_are_used_instead_of_being_read_back_from_the_12_percent(api, client_record):
    dev = add(api, client_record, "Dev")
    # 18,000 wages but the employee's share is on the Rs 15,000 ceiling (1,800): reading it back from 12% would say 15,000 wages.
    made = run(api, client_record, [line(dev, gross_paise=40_000_00, pf_employee_paise=1_800_00, pf_employer_paise=1_800_00, tds_paise=0, pf_wages_paise=18_000_00)])
    assert made.status_code == 201, made.content
    row = working(api, client_record)["rows"][0]
    assert row["pf_wages_paise"] == 18_000_00
    assert row["eps_paise"] == 124_950, "pension is on the Rs 15,000 ceiling, not on all the wages"


def test_wages_more_than_the_gross_are_refused(api, client_record):
    eve = add(api, client_record, "Eve")
    made = run(api, client_record, [line(eve, gross_paise=20_000_00, pf_employee_paise=1_800_00, pf_employer_paise=1_800_00, tds_paise=0, pf_wages_paise=25_000_00)])
    assert made.status_code in (400, 422) and "PF wages" in made.content.decode()


def test_a_line_with_no_wages_entered_still_reads_them_back(api, client_record, booked):
    assert working(api, client_record)["rows"][0]["pf_wages_paise"] == 12_000_00
