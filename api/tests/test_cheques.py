"""The cheque register: issued and received cheques, post-dated ones, their status, and who may change them."""

from __future__ import annotations

import datetime

import pytest

from api.tests.conftest import member, sign_in
from api.tests.test_bills import base, make_party
from banking.models import BankAccount
from core.db.session import firm_context
from core.models import Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def account(firm, client_record, statement):
    with firm_context(firm.pk):
        return str(BankAccount.objects.filter(client=client_record).first().pk)


def url(client, tail=""):
    return f"{base(client)}/cheques/{tail}"


def write(api, client, account, **over):
    today = datetime.date.today()
    body = {"bank_account": account, "direction": "ISSUED", "number": "000101", "cheque_date": today.isoformat(), "issued_on": today.isoformat(), "amount_paise": 5_000_00, "payee_name": "Sharma Traders", **over}
    return api.post(url(client), body, format="json")


def test_a_cheque_is_recorded_with_who_it_is_for_and_audited(api, client_record, account):
    party = make_party(api, client_record)
    done = write(api, client_record, account, party=party["id"], payee_name="")
    assert done.status_code == 201, done.content
    body = done.json()
    assert body["status"] == "PENDING" and body["print_name"] == party["canonical_name"] and body["is_post_dated"] is False
    assert body["bank_label"].endswith(body["bank_label"][-4:]) and "••••" in body["bank_label"]
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "CHEQUE"}).json()
    assert any("Cheque 000101" in r["label"] for r in audit["results"])


def test_a_cheque_dated_after_it_was_issued_is_post_dated_and_shows_in_the_summary(api, client_record, account):
    today = datetime.date.today()
    later = today + datetime.timedelta(days=45)
    assert write(api, client_record, account, number="000201", cheque_date=later.isoformat(), amount_paise=2_000_00).json()["is_post_dated"] is True
    assert write(api, client_record, account, number="000202", direction="RECEIVED", cheque_date=later.isoformat(), amount_paise=3_000_00).status_code == 201
    soon = today + datetime.timedelta(days=3)
    assert write(api, client_record, account, number="000203", cheque_date=soon.isoformat(), amount_paise=1_000_00).status_code == 201
    body = api.get(url(client_record, "pdc/")).json()
    assert (body["issued_paise"], body["received_paise"]) == (3_000_00, 3_000_00), "all three are dated after the day they were written"
    assert sum(m["issued_paise"] for m in body["by_month"]) == 3_000_00
    assert [c["number"] for c in body["due_soon"]] == ["000203"]


def test_clearing_and_bouncing_set_the_status_and_day_and_a_cleared_one_cannot_be_edited_or_removed(api, client_record, account):
    cheque = write(api, client_record, account).json()
    done = api.post(url(client_record, f"{cheque['id']}/status/"), {"status": "CLEARED", "on": "2026-01-05"}, format="json")
    assert done.status_code == 200 and done.json()["status"] == "CLEARED" and done.json()["status_on"] == "2026-01-05"
    assert api.patch(url(client_record, f"{cheque['id']}/"), {"amount_paise": 1}, format="json").status_code == 400
    assert api.delete(url(client_record, f"{cheque['id']}/")).status_code == 400
    back = api.post(url(client_record, f"{cheque['id']}/status/"), {"status": "PENDING"}, format="json").json()
    assert back["status"] == "PENDING" and back["status_on"] is None
    assert api.delete(url(client_record, f"{cheque['id']}/")).status_code == 204


def test_a_pending_cheque_more_than_three_months_old_is_stale(api, client_record, account):
    old = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
    made = write(api, client_record, account, number="000301", cheque_date=old, issued_on=old).json()
    assert made["is_stale"] is True
    assert [c["number"] for c in api.get(url(client_record, "pdc/")).json()["stale"]] == ["000301"]


def test_the_list_filters_and_a_repeated_number_or_bad_input_is_refused(api, client_record, account):
    write(api, client_record, account, number="000401")
    write(api, client_record, account, number="000402", direction="RECEIVED")
    assert [c["number"] for c in api.get(url(client_record), {"direction": "RECEIVED"}).json()["results"]] == ["000402"]
    assert [c["number"] for c in api.get(url(client_record), {"q": "000401"}).json()["results"]] == ["000401"]
    assert write(api, client_record, account, number="000401").status_code == 400
    assert write(api, client_record, account, number="12 34").status_code == 400
    assert write(api, client_record, account, number="000403", amount_paise=0).status_code == 400
    assert write(api, client_record, "00000000-0000-0000-0000-000000000000", number="000404").status_code == 400


def test_a_reader_can_look_but_not_write(api, client_record, account, firm):
    write(api, client_record, account)
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert reader.get(url(client_record)).status_code == 200
    assert reader.post(url(client_record), {}, format="json").status_code == 403
    assert reader.get(url(client_record, "accounts/")).status_code == 200
