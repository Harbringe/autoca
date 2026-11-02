"""Cost centres, tagging journal lines to them, budgets, and the reports that read both."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from core.db.session import firm_context
from ledger.models import JournalLine

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def purchase(api, client_record):
    vendor = make_party(api, client_record)
    expense = make_ledger(api, client_record, "Contract Work", "DIRECT_EXPENSE")
    made = post_bill(api, client_record, voucher(vendor, expense, heads=[{"ledger": expense["id"], "amount_paise": 10_000_000}], cgst_paise=0, sgst_paise=0))
    assert made.status_code == 201, made.content
    return expense


def expense_line(firm, client, ledger_id):
    with firm_context(firm.pk):
        return str(JournalLine.objects.get(entry__client=client, ledger_account_id=ledger_id).pk)


def centre(api, client, name):
    done = api.post(f"{base(client)}/cost-centres/", {"name": name}, format="json")
    assert done.status_code == 201, done.content
    return done.json()["id"]


def test_a_cost_centre_is_made_once_per_name_and_audited(api, client_record):
    centre(api, client_record, "Pune Site")
    assert api.post(f"{base(client_record)}/cost-centres/", {"name": "pune site"}, format="json").status_code == 400
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "CENTRE"}).json()
    assert any("Cost centre: Pune Site" in r["label"] for r in audit["results"])


def test_a_line_split_across_centres_shows_in_the_report_with_the_rest_unallocated(api, client_record, firm, purchase):
    pune, goa = centre(api, client_record, "Pune Site"), centre(api, client_record, "Goa Site")
    line = expense_line(firm, client_record, purchase["id"])
    done = api.post(
        f"{base(client_record)}/cost-centre-tags/",
        {"line": line, "allocations": [{"cost_centre": pune, "amount_paise": 6_000_000}, {"cost_centre": goa, "amount_paise": 3_000_000}]},
        format="json",
    )
    assert done.status_code == 201, done.content
    body = api.get(f"{base(client_record)}/cost-centre-report/", {"fy": 2025}).json()
    by_name = {c["name"]: c for c in body["centres"]}
    assert by_name["Pune Site"]["expense_paise"] == 6_000_000 and by_name["Goa Site"]["net_paise"] == -3_000_000
    assert by_name["Pune Site"]["ledgers"][0]["ledger"] == "Contract Work"
    assert body["unallocated_expense_paise"] == 1_000_000


def test_tags_can_be_replaced_and_cleared_and_read_back_by_entry(api, client_record, firm, purchase):
    pune = centre(api, client_record, "Pune Site")
    line = expense_line(firm, client_record, purchase["id"])
    api.post(f"{base(client_record)}/cost-centre-tags/", {"line": line, "allocations": [{"cost_centre": pune, "amount_paise": 1_000_000}]}, format="json")
    with firm_context(firm.pk):
        entry = str(JournalLine.objects.get(pk=line).entry_id)
    got = api.get(f"{base(client_record)}/cost-centre-tags/", {"entry": entry}).json()
    assert [(t["cost_centre_name"], t["amount_paise"]) for t in got] == [("Pune Site", 1_000_000)]
    api.post(f"{base(client_record)}/cost-centre-tags/", {"line": line, "allocations": []}, format="json")
    assert api.get(f"{base(client_record)}/cost-centre-tags/", {"entry": entry}).json() == []


def test_tagging_refuses_more_than_the_line_a_non_pl_line_a_repeat_and_another_clients_centre(api, client_record, firm, purchase):
    pune = centre(api, client_record, "Pune Site")
    line = expense_line(firm, client_record, purchase["id"])
    url = f"{base(client_record)}/cost-centre-tags/"
    assert api.post(url, {"line": line, "allocations": [{"cost_centre": pune, "amount_paise": 10_000_001}]}, format="json").status_code == 400
    assert api.post(url, {"line": line, "allocations": [{"cost_centre": pune, "amount_paise": 1}, {"cost_centre": pune, "amount_paise": 2}]}, format="json").status_code == 400
    assert api.post(url, {"line": line, "allocations": [{"cost_centre": "00000000-0000-0000-0000-000000000000", "amount_paise": 5}]}, format="json").status_code == 400
    with firm_context(firm.pk):
        party_line = str(JournalLine.objects.filter(entry__client=client_record).exclude(ledger_account_id=purchase["id"]).first().pk)
    assert api.post(url, {"line": party_line, "allocations": [{"cost_centre": pune, "amount_paise": 5}]}, format="json").status_code == 400


def test_a_centre_with_tagged_lines_cannot_be_removed(api, client_record, firm, purchase):
    pune = centre(api, client_record, "Pune Site")
    line = expense_line(firm, client_record, purchase["id"])
    api.post(f"{base(client_record)}/cost-centre-tags/", {"line": line, "allocations": [{"cost_centre": pune, "amount_paise": 5}]}, format="json")
    assert api.delete(f"{base(client_record)}/cost-centres/{pune}/").status_code == 400
    api.post(f"{base(client_record)}/cost-centre-tags/", {"line": line, "allocations": []}, format="json")
    assert api.delete(f"{base(client_record)}/cost-centres/{pune}/").status_code == 204


def set_budget(api, client, ledger, months, fy=2025):
    return api.put(f"{base(client)}/budgets/set/", {"fy": fy, "ledger": ledger, "months": months}, format="json")


def test_a_budget_is_set_compared_with_the_books_and_audited(api, client_record, purchase):
    done = set_budget(api, client_record, purchase["id"], {"2025-10": 8_000_000, "2025-11": 5_000_000})
    assert done.status_code == 200, done.content
    assert done.json()[0]["total_paise"] == 13_000_000
    body = api.get(f"{base(client_record)}/budgets/variance/", {"fy": 2025}).json()
    (row,) = body["ledgers"]
    months = {m["month"]: m for m in row["months"]}
    assert months["2025-10"]["actual_paise"] == 10_000_000 and months["2025-10"]["variance_paise"] == 2_000_000, "overspent by 20,000"
    assert months["2025-11"]["actual_paise"] == 0 and months["2025-11"]["variance_paise"] == -5_000_000
    assert months["2025-04"]["budget_paise"] is None
    assert (row["budget_paise"], row["actual_paise"], row["variance_paise"]) == (13_000_000, 10_000_000, -3_000_000)
    through = api.get(f"{base(client_record)}/budgets/variance/", {"fy": 2025, "through": "2025-10"}).json()["ledgers"][0]
    assert (through["budget_paise"], through["variance_paise"]) == (8_000_000, 2_000_000)
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "BUDGET"}).json()
    assert any("Budget: Contract Work" in r["label"] for r in audit["results"])


def test_a_month_is_cleared_with_null_and_bad_months_ledgers_and_amounts_are_refused(api, client_record, purchase):
    set_budget(api, client_record, purchase["id"], {"2025-10": 8_000_000})
    cleared = set_budget(api, client_record, purchase["id"], {"2025-10": None})
    assert cleared.status_code == 200 and cleared.json() == []
    assert set_budget(api, client_record, purchase["id"], {"2026-04": 5}).status_code == 400, "April 2026 is the next financial year"
    assert set_budget(api, client_record, purchase["id"], {"October": 5}).status_code == 400
    assert set_budget(api, client_record, purchase["id"], {"2025-10": -5}).status_code == 400
    assert set_budget(api, client_record, "00000000-0000-0000-0000-000000000000", {"2025-10": 5}).status_code == 404
    assert api.get(f"{base(client_record)}/budgets/").status_code == 400, "a year is needed"


def test_an_income_ledger_over_budget_is_a_positive_variance(api, client_record):
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")
    sale = {"kind": "SALES", "party": customer["id"], "reference": "S-1", "bill_date": "2025-10-05", "heads": [{"ledger": sales["id"], "amount_paise": 5_000_000}], "cgst_paise": 0, "sgst_paise": 0}
    assert post_bill(api, client_record, sale).status_code == 201
    set_budget(api, client_record, sales["id"], {"2025-10": 4_000_000})
    row = api.get(f"{base(client_record)}/budgets/variance/", {"fy": 2025}).json()["ledgers"][0]
    assert row["is_income"] is True and row["months"][6]["actual_paise"] == 5_000_000 and row["months"][6]["variance_paise"] == 1_000_000
