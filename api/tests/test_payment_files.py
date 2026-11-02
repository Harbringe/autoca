"""Where to pay a party, and the bank payment file: details stay encrypted, limits are enforced, nothing is booked."""

from __future__ import annotations

import csv
import datetime
import io

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_bills import base, make_ledger, make_party, post_bill, voucher
from banking.models import BankAccount
from core.db.session import firm_context
from core.models import Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


@pytest.fixture
def account(firm, client_record, statement):
    with firm_context(firm.pk):
        return str(BankAccount.objects.filter(client=client_record).first().pk)


@pytest.fixture
def owed(api, client_record):
    vendor = make_party(api, client_record)
    works = make_ledger(api, client_record, "Contract Work", "DIRECT_EXPENSE")
    body = voucher(vendor, works, heads=[{"ledger": works["id"], "amount_paise": 10_000_000}], cgst_paise=0, sgst_paise=0)
    assert post_bill(api, client_record, body).status_code == 201
    return vendor


def details_url(client, party):
    return f"{base(client)}/parties/{party['id']}/payment-details/"


def save_details(api, client, party, **over):
    body = {"account_number": "50100123456789", "ifsc": "HDFC0001234", "account_name": "Ravi Traders", **over}
    return api.put(details_url(client, party), body, format="json")


def ask(api, client, account, party, **over):
    body = {"bank_account": account, "mode": "NEFT", "payment_date": TOMORROW, "items": [{"party": party["id"], "amount_paise": 10_000_000}], **over}
    return api.post(f"{base(client)}/payment-files/", body, format="json")


def test_payment_details_are_saved_and_only_the_last_four_digits_come_back(api, client_record, owed):
    assert api.get(details_url(client_record, owed)).json()["ready"] is False
    done = save_details(api, client_record, owed)
    assert done.status_code == 200, done.content
    body = done.json()
    assert body == {"ifsc": "HDFC0001234", "account_name": "Ravi Traders", "account_last4": "6789", "ready": True}
    assert "50100123456789" not in str(api.get(f"{base(client_record)}/parties/{owed['id']}/").content)
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "PARTY"}).json()
    assert any("Payment details" in r["label"] for r in audit["results"]) and "50100123456789" not in str(audit)


def test_a_bad_ifsc_or_account_number_is_refused_and_a_reader_cannot_save(api, client_record, owed, firm):
    assert save_details(api, client_record, owed, ifsc="HDFC123").status_code == 400
    assert save_details(api, client_record, owed, account_number="12").status_code == 400
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert reader.put(details_url(client_record, owed), {"ifsc": "HDFC0001234"}, format="json").status_code == 403


def test_the_payables_list_says_who_is_owed_and_who_can_be_paid(api, client_record, owed):
    (row,) = api.get(f"{base(client_record)}/payment-files/").json()
    assert (row["name"], row["open_paise"], row["bills"], row["ready"]) == ("Ravi Traders", 10_000_000, 1, False)
    save_details(api, client_record, owed)
    assert api.get(f"{base(client_record)}/payment-files/").json()[0]["ready"] is True


def test_the_file_has_one_line_per_payee_with_the_account_in_full_and_books_nothing(api, client_record, owed, account):
    save_details(api, client_record, owed)
    before = api.get(f"{base(client_record)}/payment-files/").json()[0]["open_paise"]
    done = ask(api, client_record, account, owed, items=[{"party": owed["id"], "amount_paise": 5_000_050, "narration": "=cmd|' /C calc'!A0"}])
    assert done.status_code == 200, done.content
    assert done["Content-Type"].startswith("text/csv") and "no-store" in done["Cache-Control"] and "attachment" in done["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(done.content.decode())))
    assert rows[0][0] == "Payment mode" and len(rows) == 2
    assert rows[1][:5] == ["NEFT", "Ravi Traders", "50100123456789", "HDFC0001234", "50000.50"]
    assert not rows[1][6].startswith("="), "a narration cannot start a spreadsheet formula"
    assert api.get(f"{base(client_record)}/payment-files/").json()[0]["open_paise"] == before


def test_limits_missing_details_and_repeats_are_refused_in_words(api, client_record, owed, account):
    no_details = ask(api, client_record, account, owed)
    assert no_details.status_code == 400 and "no bank details" in str(no_details.json())
    save_details(api, client_record, owed)
    small_rtgs = ask(api, client_record, account, owed, mode="RTGS", items=[{"party": owed["id"], "amount_paise": 100_000_00}])
    assert small_rtgs.status_code == 400 and "RTGS" in str(small_rtgs.json())
    big_imps = ask(api, client_record, account, owed, mode="IMPS", items=[{"party": owed["id"], "amount_paise": 600_000_00}])
    assert big_imps.status_code == 400 and "IMPS" in str(big_imps.json())
    twice = ask(api, client_record, account, owed, items=[{"party": owed["id"], "amount_paise": 5}, {"party": owed["id"], "amount_paise": 6}])
    assert twice.status_code == 400
    past = ask(api, client_record, account, owed, payment_date="2020-01-01")
    assert past.status_code == 400
    assert ask(api, client_record, "00000000-0000-0000-0000-000000000000", owed).status_code == 404


def test_only_someone_who_may_approve_can_prepare_a_file(api, client_record, owed, account, firm):
    save_details(api, client_record, owed)
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert ask(reader, client_record, account, owed).status_code == 403
