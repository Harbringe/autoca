"""Outstanding payables and receivables, and a party's statement, from the outside."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from api.tests.conftest import member, sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from core.models import Role
from core.provisioning import create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def bill(api, client_record, party, purchases, reference, amount, on):
    body = voucher(
        party, purchases, reference=reference, bill_date=on, cgst_paise=0, sgst_paise=0,
        heads=[{"ledger": purchases["id"], "amount_paise": amount}],
    )
    response = post_bill(api, client_record, body)
    assert response.status_code == 201, response.content
    return response.json()


@pytest.fixture
def ravi_with_two_bills(api, client_record):
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    bill(api, client_record, party, purchases, "OLD", 1_000_00, "2025-04-01")
    bill(api, client_record, party, purchases, "NEW", 4_000_00, "2025-07-20")
    return party


def outstanding(api, client_record, **params):
    return api.get(f"{base(client_record)}/outstanding/", params)


# ---------------------------------------------------------------------------
# Outstanding
# ---------------------------------------------------------------------------


def test_outstanding_payables_are_listed_by_party_and_aged(api, client_record, ravi_with_two_bills):
    response = outstanding(api, client_record, side="payables", as_of="2025-08-01")

    assert response.status_code == 200, response.content
    report = response.json()
    assert report["side"] == "payables" and report["as_of"] == "2025-08-01"
    assert report["buckets"] == ["0-30", "31-60", "61-90", "Over 90"]
    (party,) = report["parties"]
    assert party["name"] == "Ravi Traders" and party["gstin_last4"] == "K1Z7"
    assert [(b["reference"], b["age_days"], b["bucket"], b["open_paise"]) for b in party["bills"]] == [
        ("OLD", 122, "Over 90", 1_000_00), ("NEW", 12, "0-30", 4_000_00),
    ]
    assert party["total_paise"] == 5_000_00 and party["total_display"] == "₹5,000.00"
    assert party["bucket_paise"] == {"0-30": 4_000_00, "31-60": 0, "61-90": 0, "Over 90": 1_000_00}
    assert report["total_paise"] == 5_000_00 and report["total_display"] == "₹5,000.00"


def test_the_date_asked_for_decides_what_is_in_the_report(api, client_record, ravi_with_two_bills):
    june = outstanding(api, client_record, as_of="2025-06-01").json()

    assert [b["reference"] for b in june["parties"][0]["bills"]] == ["OLD"]
    assert june["total_paise"] == 1_000_00


def test_receivables_are_a_separate_report(api, client_record, ravi_with_two_bills):
    assert outstanding(api, client_record, side="receivables", as_of="2025-08-01").json()["parties"] == []


def test_a_bad_side_or_date_says_what_to_send(api, client_record, ravi_with_two_bills):
    side = outstanding(api, client_record, side="owed")
    date = outstanding(api, client_record, as_of="1-8-2025")

    assert side.status_code == 400 and "side" in side.json()["fields"]
    assert date.status_code == 400 and "YYYY-MM-DD" in date.json()["fields"]["as_of"][0]


def test_read_only_members_can_read_the_reports(api, client_record, ravi_with_two_bills, reader):
    assert outstanding(sign_in(reader.user), client_record, as_of="2025-08-01").status_code == 200


def test_anonymous_requests_are_refused(client_record):
    assert APIClient().get(f"{base(client_record)}/outstanding/").status_code in (401, 403)


def test_another_firm_cannot_read_this_clients_reports(client_record):
    outsider = sign_in(member(create_firm("Somebody Else"), Role.SENIOR_CA, "them@example.test").user)
    nobody = "00000000-0000-0000-0000-000000000000"

    assert outsider.get(f"{base(client_record)}/outstanding/").status_code == 404
    assert outsider.get(f"{base(client_record)}/parties/{nobody}/statement/").status_code == 404


# ---------------------------------------------------------------------------
# The statement of account
# ---------------------------------------------------------------------------


def test_a_statement_shows_the_partys_account_with_a_running_balance(api, client_record, ravi_with_two_bills):
    party = api.get(f"{base(client_record)}/parties/{ravi_with_two_bills['id']}/").json()

    response = api.get(
        f"{base(client_record)}/parties/{party['id']}/statement/", {"date_from": "2025-04-01", "date_to": "2025-12-31"}
    )

    assert response.status_code == 200, response.content
    statement = response.json()
    assert statement["name"] == "Ravi Traders" and statement["opening_paise"] == 0
    assert [(r["voucher_type"], r["credit_paise"], r["balance_paise"]) for r in statement["rows"]] == [
        ("Purchase", 1_000_00, -1_000_00), ("Purchase", 4_000_00, -5_000_00),
    ]
    assert statement["rows"][0]["bill"] is not None and statement["rows"][0]["entry"]
    assert statement["closing_paise"] == -5_000_00 and statement["closing_display"] == "-₹5,000.00"
    assert (statement["total_debit_paise"], statement["total_credit_paise"]) == (0, 5_000_00)


def test_a_statement_for_a_later_period_opens_with_what_went_before(api, client_record, ravi_with_two_bills):
    response = api.get(
        f"{base(client_record)}/parties/{ravi_with_two_bills['id']}/statement/",
        {"date_from": "2025-06-01", "date_to": "2025-12-31"},
    )

    statement = response.json()
    assert statement["opening_paise"] == -1_000_00
    assert [r["credit_paise"] for r in statement["rows"]] == [4_000_00]


def test_a_statement_that_ends_before_it_starts_is_refused(api, client_record, ravi_with_two_bills):
    response = api.get(
        f"{base(client_record)}/parties/{ravi_with_two_bills['id']}/statement/",
        {"date_from": "2025-06-01", "date_to": "2025-05-01"},
    )

    assert response.status_code == 400 and "date_to" in response.json()["fields"]


def test_a_party_with_no_account_yet_has_an_empty_statement(api, client_record):
    party = make_party(api, client_record, "Never Used", gstin="")

    response = api.get(f"{base(client_record)}/parties/{party['id']}/statement/", {"date_from": "2025-04-01", "date_to": "2025-12-31"})

    assert response.status_code == 200
    assert response.json()["rows"] == [] and response.json()["closing_paise"] == 0


# ---------------------------------------------------------------------------
# Open items
# ---------------------------------------------------------------------------


def open_items(api, client_record, **params):
    return api.get(f"{base(client_record)}/open-items/", params)


def test_open_items_lists_what_does_not_tie_out_oldest_first(api, client_record, ravi_with_two_bills):
    response = open_items(api, client_record)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 2
    assert [i["kind"] for i in body["items"]] == ["bill_without_document", "bill_without_document"]
    first = body["items"][0]
    assert first["since"] == "2025-04-01" and first["age_days"] > 0
    assert first["amount_paise"] == 1_000_00 and first["amount_display"] == "₹1,000.00"
    assert first["link"]["type"] == "bill" and "OLD" in first["summary"]
    assert first["title"]
    named = {k["kind"]: k["count"] for k in body["kinds"]}
    assert named["bill_without_document"] == 2 and named["payment_unallocated"] == 0
    assert {"payment_bypasses_bills", "payment_needs_invoice", "party_out_of_balance", "money_on_account"} <= set(named)


def test_open_items_can_be_narrowed_to_one_kind_and_still_counts_the_rest(api, client_record, ravi_with_two_bills):
    body = open_items(api, client_record, kind="payment_unallocated").json()

    assert body["items"] == []
    assert body["count"] == 2  # the count is for everything open, not just what is shown


def test_an_unknown_kind_says_what_the_kinds_are(api, client_record):
    response = open_items(api, client_record, kind="nonsense")

    assert response.status_code == 400 and "bill_without_document" in response.json()["fields"]["kind"][0]


def test_open_items_are_visible_to_read_only_members_but_not_to_another_firm(client_record, reader):
    assert open_items(sign_in(reader.user), client_record).status_code == 200


def test_another_firm_cannot_read_this_clients_open_items(client_record):
    outsider = sign_in(member(create_firm("Somebody Else"), Role.SENIOR_CA, "them@example.test").user)

    assert open_items(outsider, client_record).status_code == 404


# ---------------------------------------------------------------------------
# Saying why a payment has no invoice
# ---------------------------------------------------------------------------


def paid_to_a_supplier_with_bills(api, client_record, statement):
    from classify.engine import review_queue

    row = review_queue(client_record).filter(transaction__narration__icontains="AXOMB10000000001").first()
    party = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    bill(api, client_record, party, purchases, "INV-1", 1_000_00, "2025-04-01")
    expense = make_ledger(api, client_record, "Office Expenses", "INDIRECT_EXPENSE")
    placed = api.post(
        f"{V1}/classifications/{row.pk}/review/", {"ledger": expense["id"], "party": party["id"], "learn": False}, format="json"
    )
    assert placed.status_code == 200, placed.content
    posted = api.post(f"{base(client_record)}/approvals/", {"classifications": [str(row.pk)]}, format="json")
    assert posted.status_code == 201, posted.content
    return posted.json()[0]["id"]


def test_a_payment_that_goes_round_the_bills_is_listed_until_someone_says_why(api, client_record, statement):
    entry = paid_to_a_supplier_with_bills(api, client_record, statement)

    listed = open_items(api, client_record, kind="payment_bypasses_bills").json()["items"]
    assert len(listed) == 1 and listed[0]["link"] == {"type": "entry", "id": entry}

    said = api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NO_INVOICE_EXPECTED"}, format="json")
    assert said.status_code == 200 and said.json() == {"status": "NO_INVOICE_EXPECTED"}
    assert open_items(api, client_record, kind="payment_bypasses_bills").json()["items"] == []


def test_a_payment_waiting_for_its_invoice_stays_listed_under_its_own_kind(api, client_record, statement):
    entry = paid_to_a_supplier_with_bills(api, client_record, statement)

    api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NEEDS_INVOICE"}, format="json")

    assert open_items(api, client_record, kind="payment_bypasses_bills").json()["items"] == []
    waiting = open_items(api, client_record, kind="payment_needs_invoice").json()["items"]
    assert len(waiting) == 1 and "waiting for its invoice" in waiting[0]["summary"]


def test_saying_why_can_be_unsaid(api, client_record, statement):
    entry = paid_to_a_supplier_with_bills(api, client_record, statement)
    api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NO_INVOICE_EXPECTED"}, format="json")

    api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": ""}, format="json")

    assert len(open_items(api, client_record, kind="payment_bypasses_bills").json()["items"]) == 1


def test_a_status_must_be_one_of_the_choices_and_a_read_only_member_may_not_set_one(api, client_record, statement, reader):
    entry = paid_to_a_supplier_with_bills(api, client_record, statement)

    assert api.post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "MAYBE"}, format="json").status_code == 400
    refused = sign_in(reader.user).post(f"{V1}/journal-entries/{entry}/bill-status/", {"status": "NEEDS_INVOICE"}, format="json")
    assert refused.status_code == 403


def test_a_bill_voucher_has_no_such_status(api, client_record, ravi_with_two_bills):
    bills = api.get(f"{base(client_record)}/bills/").json()["results"]

    response = api.post(f"{V1}/journal-entries/{bills[0]['entry']}/bill-status/", {"status": "NEEDS_INVOICE"}, format="json")

    assert response.status_code == 409 and response.json()["code"] == "wrong_entry_kind"
