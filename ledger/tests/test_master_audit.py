"""The master audit recorder: plain JSON snapshots, and nothing written for an edit that changed nothing."""

from __future__ import annotations

import datetime
import decimal
import uuid

import pytest

from classify.models import LedgerGroup as G
from core.db.session import firm_context
from ledger.audit import LEDGER_FIELDS, PARTY_FIELDS, record_master_change, snapshot
from ledger.models import MasterChange
from ledger.tests.support import make_ledger
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    client,
    firm,
    member,
    senior,
)

pytestmark = pytest.mark.django_db


def test_a_snapshot_is_plain_json_and_a_relation_is_its_id(firm, client):
    with firm_context(firm.pk):
        ledger = make_ledger(client, "Rent", G.INDIRECT_EXPENSE)
        shot = snapshot(ledger, LEDGER_FIELDS)
    assert shot["name"] == "Rent" and shot["group"] == G.INDIRECT_EXPENSE and shot["is_active"] is True
    import json

    json.dumps(shot)  # nothing that cannot be written


def test_a_party_snapshot_never_carries_the_gstin(firm, client):
    from classify.models import Party

    with firm_context(firm.pk):
        party = Party.objects.create(firm_id=firm.pk, client=client, canonical_name="Acme")
        shot = snapshot(party, PARTY_FIELDS)
    assert "gstin" not in shot and "gstin_enc" not in shot and shot["has_gstin"] is False


def test_an_edit_that_changed_nothing_writes_nothing_and_a_real_one_does(firm, client, senior):
    with firm_context(firm.pk):
        same = record_master_change(client, "LEDGER", uuid.uuid4(), "EDITED", label="Rent", before={"a": 1}, after={"a": 1}, actor=senior.user)
        real = record_master_change(client, "LEDGER", uuid.uuid4(), "EDITED", label="Rent", before={"a": 1}, after={"a": 2}, actor=senior.user)
        assert same is None and real is not None
        assert MasterChange.objects.filter(client=client).count() == 1


def test_values_that_are_not_json_are_made_plain():
    from ledger.audit import _plain

    assert _plain(uuid.UUID(int=1)) == "00000000-0000-0000-0000-000000000001"
    assert _plain(decimal.Decimal("18.00")) == "18.00"
    assert _plain(datetime.date(2025, 4, 1)) == "2025-04-01"
    assert _plain("x") == "x" and _plain(3) == 3 and _plain(None) is None
