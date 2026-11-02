"""Bills of materials and production runs: components used up at average cost, finished goods brought in, shortages refused."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def stock(api, client, name, qty, value, unit="kg"):
    done = api.post(
        f"{base(client)}/stock-entries/",
        {"kind": "OPENING", "entry_date": "2025-04-01", "direction": "IN", "name": name, "unit": unit, "quantity": qty, "value_paise": value},
        format="json",
    )
    assert done.status_code == 201, done.content


def make_bom(api, client, **over):
    body = {
        "name": "Masala Mix", "unit": "pkt", "output_quantity": "10",
        "components": [{"name": "Chilli", "unit": "kg", "quantity": "2"}, {"name": "Salt", "unit": "kg", "quantity": "1.5"}], **over,
    }
    return api.post(f"{base(client)}/boms/", body, format="json")


def run(api, client, bom, quantity="20", **over):
    return api.post(f"{base(client)}/boms/{bom['id']}/produce/", {"quantity": quantity, "entry_date": "2025-06-10", **over}, format="json")


def report(api, client):
    return {i["name"]: i for i in api.get(f"{base(client)}/reports/inventory/", {"fy": 2025}).json()["items"]}


@pytest.fixture
def stocked(api, client_record):
    stock(api, client_record, "Chilli", "100", 20_000_00)  # Rs 200 a kg
    stock(api, client_record, "Salt", "50", 1_000_00)  # Rs 20 a kg


def test_a_bill_of_materials_is_made_once_per_item_and_audited(api, client_record):
    done = make_bom(api, client_record)
    assert done.status_code == 201, done.content
    assert done.json()["components"][0] == {"name": "Chilli", "unit": "kg", "quantity": "2.000"}
    assert make_bom(api, client_record, name="masala mix").status_code == 400
    audit = api.get(f"{base(client_record)}/audit-trail/", {"kind": "BOM"}).json()
    assert any("Bill of materials: Masala Mix" in r["label"] for r in audit["results"])


def test_a_bad_bill_is_refused(api, client_record):
    assert make_bom(api, client_record, components=[]).status_code == 400
    assert make_bom(api, client_record, components=[{"name": "A", "quantity": "1"}, {"name": "a", "quantity": "2"}]).status_code == 400
    assert make_bom(api, client_record, components=[{"name": "Masala Mix", "quantity": "1"}]).status_code == 400
    assert make_bom(api, client_record, components=[{"name": "A", "quantity": "0"}]).status_code == 400
    assert make_bom(api, client_record, output_quantity="0").status_code == 400


def test_a_run_uses_up_the_components_at_average_cost_and_brings_in_the_finished_goods(api, client_record, stocked):
    bom = make_bom(api, client_record).json()
    done = run(api, client_record, bom, "20", extra_cost_paise=500_00)
    assert done.status_code == 201, done.content
    legs = {(e["direction"], e["name"]): e for e in done.json()}
    assert legs[("OUT", "Chilli")]["quantity"] == "4.000" and legs[("OUT", "Chilli")]["value_paise"] == 800_00
    assert legs[("OUT", "Salt")]["quantity"] == "3.000" and legs[("OUT", "Salt")]["value_paise"] == 60_00
    finished = legs[("IN", "Masala Mix")]
    assert finished["quantity"] == "20.000" and finished["value_paise"] == 800_00 + 60_00 + 500_00, "components plus the extra cost"
    items = report(api, client_record)
    assert items["Chilli"]["closing_qty"] == "96" and items["Salt"]["closing_qty"] == "47" and items["Masala Mix"]["closing_qty"] == "20"
    assert items["Masala Mix"]["closing_value_paise"] == 1_360_00
    assert {e["kind"] for e in done.json()} == {"PRODUCTION"}


def test_the_plan_says_what_is_needed_and_what_is_short_and_writes_nothing(api, client_record, stocked):
    bom = make_bom(api, client_record).json()
    ok = api.get(f"{base(client_record)}/boms/{bom['id']}/plan/", {"quantity": "20", "date": "2025-06-10"}).json()
    assert ok["short"] == [] and ok["cost_paise"] == 860_00 and ok["components"][0]["needed"] == "4"
    big = api.get(f"{base(client_record)}/boms/{bom['id']}/plan/", {"quantity": "1000", "date": "2025-06-10"}).json()
    assert any("Chilli: needs 200" in s for s in big["short"]) and big["components"][0]["enough"] is False
    assert report(api, client_record)["Chilli"]["closing_qty"] == "100"


def test_a_run_that_cannot_be_covered_is_refused_naming_the_short_component_and_books_nothing(api, client_record, stocked):
    bom = make_bom(api, client_record).json()
    refused = run(api, client_record, bom, "1000")
    assert refused.status_code == 400 and "Chilli: needs 200" in str(refused.json())
    assert "Masala Mix" not in report(api, client_record)


def test_removing_any_row_of_a_run_removes_the_whole_run(api, client_record, stocked):
    bom = make_bom(api, client_record).json()
    legs = run(api, client_record, bom).json()
    gone = api.post(f"{base(client_record)}/stock-entries/{legs[0]['id']}/remove/", {}, format="json")
    assert gone.status_code == 204
    items = report(api, client_record)
    assert items["Chilli"]["closing_qty"] == "100" and "Masala Mix" not in items


def test_a_production_entry_cannot_be_made_by_hand_and_a_reader_cannot_run_production(api, client_record, stocked, firm):
    from api.tests.conftest import member, sign_in
    from core.models import Role

    by_hand = api.post(
        f"{base(client_record)}/stock-entries/",
        {"kind": "PRODUCTION", "entry_date": "2025-06-10", "direction": "IN", "name": "X", "quantity": "1", "value_paise": 1},
        format="json",
    )
    assert by_hand.status_code == 400
    bom = make_bom(api, client_record).json()
    reader = sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)
    assert reader.get(f"{base(client_record)}/boms/").status_code == 200
    assert run(reader, client_record, bom).status_code == 403
