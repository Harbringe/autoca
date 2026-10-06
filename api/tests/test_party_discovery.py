"""Counterparties in the statements are proposed as parties; a person ticks the real ones."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base
from classify.models import Party, TransactionClassification
from core.db.session import firm_context

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def found(api, client_record, **params):
    return api.get(f"{base(client_record)}/parties/found/", params)


def test_the_statements_counterparties_are_proposed_without_creating_anything(api, client_record, statement):
    response = found(api, client_record, one_offs="true")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == len(body["candidates"]) > 0
    first = body["candidates"][0]
    assert first["name"] and first["count"] >= 1 and first["suggested_role"] in {"VENDOR", "CUSTOMER", "BOTH"}
    assert first["paid_display"].startswith("₹") and first["first"] <= first["last"]
    with firm_context(client_record.firm_id):
        assert not Party.objects.filter(client=client_record).exists()


def test_ranked_most_frequent_first_and_one_offs_are_left_out_by_default(api, client_record, statement):
    everyone = found(api, client_record, one_offs="true").json()["candidates"]
    repeated = found(api, client_record).json()["candidates"]

    counts = [c["count"] for c in everyone]
    assert counts == sorted(counts, reverse=True)
    assert all(c["count"] >= 2 for c in repeated) and len(repeated) <= len(everyone)


def test_ticking_a_payee_makes_the_party_and_attaches_its_rows(api, client_record, statement):
    pick = found(api, client_record, one_offs="true").json()["candidates"][0]

    made = api.post(f"{base(client_record)}/parties/found/", {"parties": [{"name": pick["name"], "role": pick["suggested_role"]}]}, format="json")

    assert made.status_code == 201 and made.json() == {"created": 1}
    with firm_context(client_record.firm_id):
        party = Party.objects.get(client=client_record)
        attached = TransactionClassification.objects.filter(party=party).count()
    assert attached == pick["count"]
    assert pick["name"] not in [c["name"] for c in found(api, client_record, one_offs="true").json()["candidates"]]


def test_ticking_the_same_payee_twice_makes_one_party(api, client_record, statement):
    pick = found(api, client_record, one_offs="true").json()["candidates"][0]
    body = {"parties": [{"name": pick["name"]}, {"name": pick["name"].lower()}]}

    api.post(f"{base(client_record)}/parties/found/", body, format="json")

    with firm_context(client_record.firm_id):
        assert Party.objects.filter(client=client_record).count() == 1


def test_a_read_only_member_can_look_but_not_create(client_record, statement, reader):
    from api.tests.conftest import sign_in

    viewer = sign_in(reader.user)

    assert found(viewer, client_record).status_code == 200
    denied = viewer.post(f"{base(client_record)}/parties/found/", {"parties": [{"name": "X"}]}, format="json")
    assert denied.status_code == 403
