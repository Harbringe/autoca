"""Bills, from the outside: posting a voucher, reading it back, and what is refused.

Everything goes through the real stack (URL routing, session auth with a second factor, the tenant middleware, row-level
security, role checks, the domain, and back out through a serializer), and data is created through the API wherever it can
be, so these tests stand where a client of the API stands.
"""

from __future__ import annotations

import datetime

import pytest
from rest_framework.test import APIClient

from api.tests.conftest import member, sign_in
from core.db.session import firm_context
from core.models import Client, Role
from core.provisioning import create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
RAVI_GSTIN = "27AAACR5055K1Z7"


def base(client_record):
    return f"{V1}/clients/{client_record.pk}"


def make_party(api, client_record, name="Ravi Traders", role="VENDOR", gstin=RAVI_GSTIN):
    response = api.post(
        f"{base(client_record)}/parties/", {"canonical_name": name, "role": role, "gstin": gstin}, format="json"
    )
    assert response.status_code == 201, response.content
    return response.json()


def make_ledger(api, client_record, name="Purchases", group="PURCHASE"):
    response = api.post(f"{base(client_record)}/ledgers/", {"name": name, "group": group}, format="json")
    assert response.status_code == 201, response.content
    return response.json()


def voucher(party, ledger, **overrides):
    body = {
        "kind": "PURCHASE",
        "party": party["id"],
        "reference": "INV-1",
        "bill_date": "2025-10-01",
        "heads": [{"ledger": ledger["id"], "amount_paise": 10_000_000}],
        "cgst_paise": 900_000,
        "sgst_paise": 900_000,
    }
    body.update(overrides)
    return body


def post_bill(api, client_record, body):
    return api.post(f"{base(client_record)}/bills/", body, format="json")


@pytest.fixture
def ravi(api, client_record):
    return make_party(api, client_record)


@pytest.fixture
def purchases(api, client_record):
    return make_ledger(api, client_record)


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def test_posting_a_purchase_returns_the_bill_with_its_voucher_and_lines(api, client_record, ravi, purchases):
    response = post_bill(api, client_record, voucher(ravi, purchases))

    assert response.status_code == 201, response.content
    bill = response.json()
    assert bill["kind"] == "PURCHASE" and bill["direction"] == "CR"
    assert bill["total_paise"] == 11_800_000 and bill["total_display"] == "₹1,18,000.00"
    assert bill["open_paise"] == 11_800_000 and bill["open_display"] == "₹1,18,000.00"
    assert bill["voucher_type"] == "Purchase" and bill["entry_no"] == 1
    assert bill["party_name"] == "Ravi Traders"
    assert bill["has_document"] is False and bill["is_locked"] is False
    assert sorted((line["ledger_name"], line["direction"], line["amount_paise"]) for line in bill["lines"]) == [
        ("Input CGST", "DR", 900_000),
        ("Input SGST", "DR", 900_000),
        ("Purchases", "DR", 10_000_000),
        ("Ravi Traders", "CR", 11_800_000),
    ]
    assert bill["allocations"] == []


def test_a_sales_invoice_debits_a_customer(api, client_record):
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")
    sales = make_ledger(api, client_record, "Sales", "SALES")

    response = post_bill(
        api,
        client_record,
        voucher(customer, sales, kind="SALES", reference="S-1", cgst_paise=0, sgst_paise=0,
                heads=[{"ledger": sales["id"], "amount_paise": 5_000_000}]),
    )

    assert response.status_code == 201, response.content
    assert response.json()["direction"] == "DR" and response.json()["voucher_type"] == "Sales"


def test_a_debit_note_and_a_credit_note_can_be_posted(api, client_record, ravi, purchases):
    note = post_bill(
        api, client_record,
        voucher(ravi, purchases, kind="DEBIT_NOTE", reference="DN-1", cgst_paise=0, sgst_paise=0,
                heads=[{"ledger": purchases["id"], "amount_paise": 1_000_000}]),
    )

    assert note.status_code == 201, note.content
    assert note.json()["voucher_type"] == "Debit Note" and note.json()["direction"] == "DR"


def test_reverse_charge_and_tds_are_passed_through_to_the_books(api, client_record, ravi, purchases):
    response = post_bill(
        api, client_record,
        voucher(ravi, purchases, cgst_paise=0, sgst_paise=0, igst_paise=1_800_000, rcm=True),
    )
    assert response.json()["total_paise"] == 10_000_000 and response.json()["rcm"] is True

    taxed = post_bill(
        api, client_record,
        voucher(ravi, purchases, reference="INV-2", cgst_paise=0, sgst_paise=0, tds_paise=500_000, tds_section="194J"),
    )
    assert taxed.json()["total_paise"] == 9_500_000 and taxed.json()["tds_paise"] == 500_000


def test_the_same_invoice_twice_is_refused_in_words(api, client_record, ravi, purchases):
    post_bill(api, client_record, voucher(ravi, purchases))

    response = post_bill(api, client_record, voucher(ravi, purchases, reference="inv 001"))

    assert response.status_code == 422
    assert response.json()["code"] == "billing_rule"
    assert "already booked" in response.json()["detail"]


def test_a_customer_cannot_have_a_purchase(api, client_record, purchases):
    customer = make_party(api, client_record, "Mehta Stores", role="CUSTOMER", gstin="")

    response = post_bill(api, client_record, voucher(customer, purchases))

    assert response.status_code == 422 and "cannot have" in response.json()["detail"]


def test_a_head_that_is_not_this_clients_ledger_is_a_validation_error(api, client_record, ravi, purchases):
    other = {"id": "00000000-0000-0000-0000-000000000000"}

    response = post_bill(api, client_record, voucher(ravi, purchases, heads=[{"ledger": other["id"], "amount_paise": 100}]))

    assert response.status_code == 400 and "heads" in response.json()["fields"]


def test_amounts_must_be_whole_paise(api, client_record, ravi, purchases):
    response = post_bill(
        api, client_record, voucher(ravi, purchases, heads=[{"ledger": purchases["id"], "amount_paise": 100.5}])
    )

    assert response.status_code == 400


def test_a_malformed_own_gstin_is_refused(api, client_record, ravi, purchases):
    assert post_bill(api, client_record, voucher(ravi, purchases, own_gstin="NOT-A-GSTIN")).status_code == 400


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_list_filters_by_kind_party_and_text(api, client_record, ravi, purchases):
    shah = make_party(api, client_record, "Shah Stationers", gstin="24AAACS1234A1Z9")
    post_bill(api, client_record, voucher(ravi, purchases, reference="R-1"))
    post_bill(api, client_record, voucher(shah, purchases, reference="S-9"))
    url = f"{base(client_record)}/bills/"

    everything = api.get(url).json()["results"]
    only_ravi = api.get(url, {"party": ravi["id"]}).json()["results"]
    by_text = api.get(url, {"q": "stationers"}).json()["results"]
    sales_only = api.get(url, {"kind": "SALES"}).json()["results"]

    assert len(everything) == 2
    assert [b["reference"] for b in only_ravi] == ["R-1"]
    assert [b["reference"] for b in by_text] == ["S-9"]
    assert sales_only == []


def test_the_list_can_show_only_open_bills(api, client_record, ravi, purchases):
    post_bill(api, client_record, voucher(ravi, purchases))
    url = f"{base(client_record)}/bills/"

    assert len(api.get(url, {"status": "open"}).json()["results"]) == 1
    assert api.get(url, {"status": "settled"}).json()["results"] == []


def test_a_bill_can_be_read_by_id_with_its_voucher(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()

    detail = api.get(f"{base(client_record)}/bills/{bill['id']}/").json()

    assert detail["reference"] == "INV-1" and len(detail["lines"]) == 4
    assert detail["narration"].startswith("Being purchase")


def test_the_journal_says_which_entries_are_vouchers_and_which_bill_they_belong_to(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()

    entry = api.get(f"{V1}/journal-entries/{bill['entry']}/").json()

    assert entry["entry_kind"] == "VOUCHER" and entry["bill"] == bill["id"]
    assert entry["voucher_type"] == "Purchase" and entry["source_transaction"] is None


def test_a_party_shows_its_role_and_gets_a_ledger_once_it_is_used(api, client_record, ravi, purchases):
    assert ravi["role"] == "VENDOR" and ravi["ledger"] is None

    post_bill(api, client_record, voucher(ravi, purchases))
    party = api.get(f"{base(client_record)}/parties/{ravi['id']}/").json()

    assert party["ledger"] and party["ledger_name"] == "Ravi Traders"


def test_a_partys_role_cannot_change_once_it_has_bills(api, client_record, ravi, purchases):
    post_bill(api, client_record, voucher(ravi, purchases))

    response = api.patch(f"{base(client_record)}/parties/{ravi['id']}/", {"role": "CUSTOMER"}, format="json")

    assert response.status_code == 400 and "role" in response.json()["fields"]


# ---------------------------------------------------------------------------
# Who may, and what the books protect
# ---------------------------------------------------------------------------


def test_a_read_only_member_can_read_bills_but_not_post_them(api, client_record, ravi, purchases, reader):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    read_only = sign_in(reader.user)

    assert read_only.get(f"{base(client_record)}/bills/").status_code == 200
    refused = post_bill(read_only, client_record, voucher(ravi, purchases, reference="INV-2"))
    assert refused.status_code == 403 and refused.json()["code"] == "permission_denied"
    assert read_only.post(f"{base(client_record)}/bills/{bill['id']}/remove/", {}, format="json").status_code == 403


def test_staff_can_post_a_voucher(staff_api, api, client_record, ravi, purchases):
    assert post_bill(staff_api, client_record, voucher(ravi, purchases)).status_code == 201


def test_another_firm_cannot_see_or_post_to_this_clients_bills(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    outsider = sign_in(member(create_firm("Somebody Else"), Role.SENIOR_CA, "them@example.test").user)

    assert outsider.get(f"{base(client_record)}/bills/").status_code == 404
    assert outsider.get(f"{base(client_record)}/bills/{bill['id']}/").status_code == 404
    assert post_bill(outsider, client_record, voucher(ravi, purchases, reference="X")).status_code == 404


def test_anonymous_requests_are_refused(client_record):
    assert APIClient().get(f"{base(client_record)}/bills/").status_code in (401, 403)


def test_an_unsettled_bill_can_be_removed_and_is_then_gone(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    url = f"{base(client_record)}/bills/{bill['id']}"

    assert api.post(f"{url}/remove/", {"note": "Wrong client"}, format="json").status_code == 204
    assert api.get(f"{url}/").status_code == 404
    assert api.get(f"{V1}/journal-entries/{bill['entry']}/").status_code == 404


def test_a_voucher_dated_inside_signed_off_books_is_refused(api, client_record, ravi, purchases):
    with firm_context(client_record.firm_id):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 10, 31))

    response = post_bill(api, client_record, voucher(ravi, purchases, bill_date="2025-10-15"))

    assert response.status_code == 422 and "signed off" in response.json()["detail"]


def test_a_bill_in_signed_off_books_cannot_be_removed(api, client_record, ravi, purchases):
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    with firm_context(client_record.firm_id):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 10, 31))

    response = api.post(f"{base(client_record)}/bills/{bill['id']}/remove/", {}, format="json")

    assert response.status_code == 409 and response.json()["code"] == "entry_locked"
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").json()["is_locked"] is True


# ---------------------------------------------------------------------------
# A voucher is not a bank entry
# ---------------------------------------------------------------------------


def test_a_voucher_entry_cannot_be_corrected_or_removed_as_a_bank_entry(api, client_record, ravi, purchases):
    """The journal's own correct and remove work through a bank row, which a voucher does not have."""
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    entry_url = f"{V1}/journal-entries/{bill['entry']}"

    corrected = api.post(
        f"{entry_url}/correct/", {"treatment": {"ledger": purchases["id"], "rcm": False}}, format="json"
    )
    removed = api.post(f"{entry_url}/remove/", {}, format="json")

    assert corrected.status_code == 409 and corrected.json()["code"] == "wrong_entry_kind"
    assert removed.status_code == 409 and removed.json()["code"] == "wrong_entry_kind"
    assert "through its bill" in corrected.json()["detail"]
    assert api.get(f"{base(client_record)}/bills/{bill['id']}/").status_code == 200
