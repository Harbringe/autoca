"""The reconciliation workflow end to end: load, match, decide, sign off."""

from __future__ import annotations

import datetime
import json

import pytest
from django.core.exceptions import PermissionDenied

from classify.models import Party
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from gst import services
from gst.models import DecisionKind, ReconDecision, RunStatus
from gst.services import GstError

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

from core.identifiers import gstin_check_character  # noqa: E402


def _gstin(first_fourteen: str) -> str:
    return first_fourteen + gstin_check_character(first_fourteen)


ME = _gstin("27AAAPL1234C1Z")
ACME = _gstin("29ABCPE1234F1Z")
BAD = ME[:-1] + ("0" if ME[-1] != "0" else "1")
PERIOD = datetime.date(2026, 8, 1)


@pytest.fixture
def firm():
    return create_firm("GST Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Arjun Nair", datetime.date(2026, 4, 1))


def member(firm, role):
    user = User.objects.create_user(
        email=f"{role.lower()}@example.com", password="correct-horse-battery-staple"
    )
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def senior(firm):
    return member(firm, Role.SENIOR_CA)


@pytest.fixture
def staff(firm):
    return member(firm, Role.STAFF)


def portal_json(gstin=ME, period="082026", invoices=None):
    invoices = invoices if invoices is not None else [
        {"inum": "INV-1", "dt": "12-08-2026", "txval": 10000, "cgst": 900, "sgst": 900},
        {"inum": "INV-2", "dt": "14-08-2026", "txval": 5000, "cgst": 450, "sgst": 450},
        {"inum": "INV-9", "dt": "20-08-2026", "txval": 700, "cgst": 63, "sgst": 63},
    ]
    return json.dumps(
        {"data": {"gstin": gstin, "rtnprd": period,
                  "docdata": {"b2b": [{"ctin": ACME, "trdnm": "Acme", "inv": invoices}]}}}
    ).encode()


REGISTER = (
    "GSTIN,Invoice No,Date,Taxable Value,CGST,SGST\n"
    f"{ACME},INV-1,12-08-2026,10000,900,900\n"       # matches
    f"{ACME},INV-2,14-08-2026,5000,450,460\n"        # amount differs
    f"{ACME},INV-3,25-08-2026,2000,180,180\n"        # not in 2B yet
).encode()


@pytest.fixture
def run(client):
    with firm_context(client.firm_id):
        reg = services.add_registration(client, ME)
        run = services.get_or_create_run(reg, PERIOD, None)
        services.load_register(run, REGISTER, "reg.csv", None)
        services.load_portal(run, portal_json(), "2b.json", None)
        services.reconcile_run(run)
        yield run


def test_reconcile_classifies_each_row_and_totals_the_credit(client, run):
    with firm_context(client.firm_id):
        s = services.summarise(run)
    assert s["counts"]["matched"] == 1
    assert s["counts"]["amount_mismatch"] == 1
    assert s["counts"]["missing_in_2b"] == 1
    assert s["counts"]["missing_in_books"] == 1
    assert s["eligible_paise"] == 1800_00
    assert s["unclaimed_in_2b_paise"] == 126_00
    assert s["unresolved"] == 1


def test_a_gstr2b_for_another_gstin_or_month_is_refused(client, run):
    with firm_context(client.firm_id):
        with pytest.raises(GstError, match="is for"):
            services.load_portal(run, portal_json(gstin=ACME), "2b.json", None)
        with pytest.raises(GstError, match="July 2026"):
            services.load_portal(run, portal_json(period="072026"), "2b.json", None)


def test_registrations_are_validated_and_unique(client):
    with firm_context(client.firm_id):
        with pytest.raises(GstError):
            services.add_registration(client, BAD)
        services.add_registration(client, ME)
        with pytest.raises(GstError, match="already"):
            services.add_registration(client, ME)
        # one PAN, a second state: allowed, and reported separately
        assert services.add_registration(client, ACME).state_code == "29"


def test_a_partys_reverse_charge_default_carries_into_the_register(client):
    with firm_context(client.firm_id):
        party = Party(firm_id=client.firm_id, client=client, canonical_name="Acme", rcm_default=True)
        party.set_gstin(ACME)
        party.save()
        reg = services.add_registration(client, ME)
        run = services.get_or_create_run(reg, PERIOD, None)
        services.load_register(run, REGISTER, "reg.csv", None)
        services.load_portal(run, portal_json(), "2b.json", None)
        services.reconcile_run(run)
        assert services.summarise(run)["counts"]["rcm"] == 3


def test_decisions_change_the_numbers_and_survive_a_rematch(client, run, staff):
    with firm_context(client.firm_id):
        mismatch = run.matches.get(kind="amount_mismatch")
        with pytest.raises(GstError):
            services.decide(run, run.matches.get(kind="missing_in_2b"),
                            DecisionKind.CLAIM_ITC, "", staff.user)
        services.decide(run, mismatch, DecisionKind.CLAIM_ITC, "supplier confirmed", staff.user)
        s = services.summarise(run)
        assert s["unresolved"] == 0
        assert s["eligible_paise"] == 1800_00 + 450_00 + 450_00  # min per head

        services.reconcile_run(run)  # rebuilds the matches; the decision is by invoice, not row
        assert services.summarise(run)["eligible_paise"] == 1800_00 + 900_00


def test_a_disallowed_credit_moves_from_eligible_to_ineligible(client, run, staff):
    with firm_context(client.firm_id):
        matched = run.matches.get(kind="matched")
        services.decide(run, matched, DecisionKind.DISALLOW_ITC, "personal use", staff.user)
        s = services.summarise(run)
        assert s["eligible_paise"] == 0
        assert s["ineligible_paise"] >= 1800_00


def test_sign_off_needs_a_senior_and_no_open_rows_then_freezes_the_run(client, run, staff, senior):
    with firm_context(client.firm_id):
        with pytest.raises(PermissionDenied):
            services.sign_off_run(run, staff.user, staff)
        with pytest.raises(GstError, match="no decision"):
            services.sign_off_run(run, senior.user, senior)

        services.decide(run, run.matches.get(kind="amount_mismatch"),
                        DecisionKind.DEFER, "next month", senior.user)
        services.sign_off_run(run, senior.user, senior)
        run.refresh_from_db()
        assert run.status == RunStatus.SIGNED_OFF and run.signed_off_by == senior.user

        with pytest.raises(GstError, match="signed off"):
            services.load_register(run, REGISTER, "reg.csv", None)
        with pytest.raises(GstError, match="signed off"):
            services.reconcile_run(run)
        with pytest.raises(GstError, match="signed off"):
            services.decide(run, run.matches.first(), DecisionKind.NOTE, "x", senior.user)


def test_decisions_are_append_only(client, run, staff):
    from django.db import DatabaseError, transaction

    with firm_context(client.firm_id):
        services.decide(run, run.matches.get(kind="matched"), DecisionKind.NOTE, "ok", staff.user)
        d = ReconDecision.objects.get()
        d.note = "changed"
        with pytest.raises(DatabaseError), transaction.atomic():
            d.save()
        with pytest.raises(DatabaseError), transaction.atomic():
            ReconDecision.objects.all().delete()
