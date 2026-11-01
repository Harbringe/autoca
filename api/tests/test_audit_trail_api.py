"""One audit trail for the books: changes to vouchers and to ledgers, parties and rules, newest first."""

from __future__ import annotations

import datetime
import uuid

import pytest

from api.tests.test_bills import (  # noqa: F401  (fixtures and helpers)
    base,
    make_ledger,
    post_bill,
    purchases,
    ravi,
    voucher,
)
from classify.models import LedgerGroup as G
from core.db.session import firm_context
from core.provisioning import create_client
from ledger.editing import record_change
from ledger.models import ChangeAction
from ledger.tests.support import make_ledger as support_ledger
from ledger.tests.support import post

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def trail(api, client, query=""):
    response = api.get(f"{base(client)}/audit-trail/{query}")
    assert response.status_code == 200, response.json()
    return response.json()["results"]


def rename(api, client, ledger, name):
    return api.patch(f"{base(client)}/ledgers/{ledger['id']}/", {"name": name}, format="json")


def test_making_and_renaming_a_ledger_are_in_the_trail_with_before_and_after(api, client_record):
    ledger = make_ledger(api, client_record, "Misc Costs", "INDIRECT_EXPENSE")
    assert rename(api, client_record, ledger, "Misc Costs 2").status_code == 200
    rows = trail(api, client_record)
    assert [(r["kind"], r["action"]) for r in rows][:2] == [("LEDGER", "EDITED"), ("LEDGER", "CREATED")], "newest first"
    edited = rows[0]
    assert edited["before"]["name"] == "Misc Costs" and edited["after"]["name"] == "Misc Costs 2"
    assert edited["label"] == "Misc Costs 2" and edited["actor_name"]


def test_a_change_that_changes_nothing_or_is_refused_leaves_no_row(api, client_record):
    ledger = make_ledger(api, client_record, "Misc Costs", "INDIRECT_EXPENSE")
    before = len(trail(api, client_record))
    assert rename(api, client_record, ledger, "Misc Costs").status_code == 200  # the same name again
    assert api.patch(f"{base(client_record)}/ledgers/{ledger['id']}/", {"group": "NOT_A_GROUP"}, format="json").status_code == 400
    assert len(trail(api, client_record)) == before


def test_removing_a_rule_is_in_the_trail(api, client_record):
    ledger = make_ledger(api, client_record, "Rent", "INDIRECT_EXPENSE")
    made = api.post(
        f"{base(client_record)}/rules/",
        {"ledger": ledger["id"], "match_type": "NARRATION_CONTAINS", "pattern": "rent", "direction": "ANY"},
        format="json",
    ).json()
    assert api.delete(f"{base(client_record)}/rules/{made['id']}/").status_code == 204
    rule_rows = [(r["action"]) for r in trail(api, client_record, "?kind=RULE")]
    assert rule_rows == ["REMOVED", "CREATED"]


def test_entry_changes_and_master_changes_come_together_in_time_order(api, firm, client_record):
    with firm_context(firm.pk):
        entry = post(client_record, datetime.date(2025, 4, 5), support_ledger(client_record, "Rent", G.INDIRECT_EXPENSE), support_ledger(client_record, "Cash", G.CASH), 100)
        record_change(entry, ChangeAction.EDITED, before={"narration": "old"}, after={"narration": "new"}, note="fixed")
    ledger = make_ledger(api, client_record, "Misc Costs", "INDIRECT_EXPENSE")
    rename(api, client_record, ledger, "Misc Costs 2")
    rows = trail(api, client_record)
    assert [r["kind"] for r in rows if r["kind"] in ("ENTRY", "LEDGER")][:3] == ["LEDGER", "LEDGER", "ENTRY"]
    assert next(r for r in rows if r["kind"] == "ENTRY")["note"] == "fixed"


def test_the_trail_can_be_filtered_by_kind_person_and_text(api, client_record):
    ledger = make_ledger(api, client_record, "Misc Costs", "INDIRECT_EXPENSE")
    rename(api, client_record, ledger, "Misc Costs 2")
    assert {r["kind"] for r in trail(api, client_record, "?kind=LEDGER")} == {"LEDGER"}
    assert trail(api, client_record, "?kind=PARTY") == []
    assert trail(api, client_record, f"?actor={uuid.uuid4()}") == []
    assert [r["action"] for r in trail(api, client_record, "?q=Costs 2")] == ["EDITED"]
    today = datetime.date.today().isoformat()
    assert trail(api, client_record, f"?from={today}&to={today}") != []
    assert trail(api, client_record, "?to=2000-01-01") == []


def test_one_clients_changes_are_not_in_anothers_trail(api, firm, client_record):
    other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    make_ledger(api, other, "Elsewhere", "INDIRECT_EXPENSE")
    assert all(r["label"] != "Elsewhere" for r in trail(api, client_record))


def test_the_trail_pages(api, client_record):
    for n in range(5):
        make_ledger(api, client_record, f"Ledger {n}", "INDIRECT_EXPENSE")
    page = api.get(f"{base(client_record)}/audit-trail/?limit=2&offset=0").json()
    assert page["count"] >= 5 and len(page["results"]) == 2
    nxt = api.get(f"{base(client_record)}/audit-trail/?limit=2&offset=2").json()
    assert {r["id"] for r in page["results"]}.isdisjoint({r["id"] for r in nxt["results"]})


def test_a_party_change_shows_that_a_gstin_was_added_but_never_the_number(api, client_record):
    made = api.post(f"{base(client_record)}/parties/", {"canonical_name": "Acme Traders", "role": "VENDOR"}, format="json")
    assert made.status_code == 201, made.json()
    edited = api.patch(f"{base(client_record)}/parties/{made.json()['id']}/", {"gstin": "27AAPFU0939F1ZV"}, format="json")
    assert edited.status_code == 200, edited.json()
    row = trail(api, client_record, "?kind=PARTY")[0]
    assert (row["before"]["has_gstin"], row["after"]["has_gstin"]) == (False, True)
    assert "27AAPFU0939F1ZV" not in str(row)


def test_posting_a_voucher_is_in_the_trail_as_created(api, firm, client_record):
    with firm_context(firm.pk):
        entry = post(client_record, datetime.date(2025, 4, 5), support_ledger(client_record, "Rent", G.INDIRECT_EXPENSE), support_ledger(client_record, "Cash", G.CASH), 12_300)
    rows = trail(api, client_record, "?kind=ENTRY")
    assert [r["action"] for r in rows] == ["CREATED"]
    assert rows[0]["label"] == f"Journal no. {entry.entry_no}, 05-04-2025"
    assert rows[0]["after"]["total_paise"] == 12_300


def test_a_voucher_taken_back_shows_as_created_then_removed(api, firm, client_record):
    with firm_context(firm.pk):
        entry = post(client_record, datetime.date(2025, 4, 5), support_ledger(client_record, "Rent", G.INDIRECT_EXPENSE), support_ledger(client_record, "Cash", G.CASH), 100)
        record_change(entry, ChangeAction.REMOVED, before={"narration": "x"}, note="wrong month")
    assert [r["action"] for r in trail(api, client_record, "?kind=ENTRY")] == ["REMOVED", "CREATED"]


def numbering(api, client, items):
    return api.put(f"{base(client)}/numbering/?fy=2025", items, format="json")


def test_changing_a_number_format_is_in_the_trail_and_changing_nothing_is_not(api, client_record):
    item = {"voucher_type": "Sales", "type_name": "", "prefix": "S/", "padding": 4}
    assert numbering(api, client_record, [item]).status_code == 200, "set"
    assert numbering(api, client_record, [item]).status_code == 200, "the same again"
    rows = trail(api, client_record, "?kind=SETTING")
    assert len(rows) == 1
    assert rows[0]["label"] == "Number format: Sales"
    assert (rows[0]["before"]["prefix"], rows[0]["after"]["prefix"], rows[0]["after"]["padding"]) == ("", "S/", 4)


def test_voucher_classes_and_types_are_in_the_trail(api, client_record):
    sales = make_ledger(api, client_record, "Sales", "SALES")
    made = api.post(f"{base(client_record)}/voucher-classes/", {"name": "Retail 18%", "voucher_type": "Sales", "head_ledger": sales["id"], "gst_rate": "18"}, format="json")
    assert made.status_code == 201, made.json()
    assert api.delete(f"{base(client_record)}/voucher-classes/{made.json()['id']}/").status_code == 204
    typed = api.post(f"{base(client_record)}/voucher-types/", {"name": "GST SALE", "parent": "Sales"}, format="json")
    assert typed.status_code == 201, typed.json()
    rows = trail(api, client_record, "?kind=SETTING")
    assert [(r["action"], r["label"]) for r in rows] == [
        ("CREATED", "Voucher type: GST SALE"),
        ("REMOVED", "Voucher class: Retail 18%"),
        ("CREATED", "Voucher class: Retail 18%"),
    ]


def test_a_removed_bill_keeps_its_creation_in_the_trail(api, client_record, ravi, purchases):
    """Removing deletes the voucher, so its "created" cannot be read from it any more: the removal's snapshot carries it."""
    bill = post_bill(api, client_record, voucher(ravi, purchases)).json()
    assert api.post(f"{base(client_record)}/bills/{bill['id']}/remove/", {"note": "Wrong client"}, format="json").status_code == 204
    rows = trail(api, client_record, "?kind=ENTRY")
    assert [r["action"] for r in rows] == ["REMOVED", "CREATED"]
    assert rows[0]["label"] == rows[1]["label"]
    assert rows[1]["at"] <= rows[0]["at"]
    assert trail(api, client_record, "?kind=ENTRY&q=Wrong")[0]["action"] == "REMOVED"
