"""What leaves the building, and what does not."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from classify.models import Vendor
from classify.pseudonymise import (
    Pseudonymiser,
    amount_band,
    looks_like_a_person,
    person_alias,
)
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = pytest.mark.django_db


def txn(narration, paise=250000, debit=True):
    return SimpleNamespace(
        pk="t1", narration=narration, amount_paise=paise, is_debit=debit
    )


@pytest.fixture
def client():
    firm = create_firm("Masking Firm")
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


def test_people_are_pseudonymised_and_businesses_are_named(client):
    p = Pseudonymiser(client, vendors=[])

    row = p.row(txn("UPI/P2A/165532563485/MADHUKAR BALAJI JADHAV/Meter/HDFC BANK LTD"))
    assert row.counterparty.startswith("P")
    assert "MADHUKAR" not in row.narration
    assert "<ACCT>" in row.narration  # the reference number
    assert row.remark == "Meter"

    row = p.row(txn("UPI/P2M/092928654106/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD"))
    assert row.counterparty == "ZERODHA BROKING LIMIT"


def test_a_known_vendor_becomes_its_alias(client):
    with firm_context(client.firm_id):
        vendor = Vendor.objects.create(
            firm_id=client.firm_id, client=client, canonical_name="Wipro GE Healthcare Pvt"
        )
    p = Pseudonymiser(client, vendors=[vendor])

    row = p.row(txn("Clg/WIPRO GE HEALTHCARE PVT/HONGKONG and S"))
    assert row.counterparty == vendor.alias_token
    assert "WIPRO" not in row.narration
    assert vendor.alias_token in row.narration
    assert p.vendor_for_alias(vendor.alias_token) == vendor
    assert p.vendor_for_alias("VMADEUP") is None


def test_the_account_holders_own_name_never_goes_out(client):
    p = Pseudonymiser(client, vendors=[], account_holder="RAMESH GOPAL DESHMUKH")
    row = p.row(txn("NEFT/MB/AXOMB20402110637/Ramesh Gopal Deshmukh/HDFC BANK/OTHERS"))
    assert row.is_self_transfer
    assert row.counterparty == "self"
    assert "Deshmukh" not in row.narration and "DESHMUKH" not in row.narration


def test_business_names_can_be_switched_off_too(client, settings):
    settings.LLM_SHARE_BUSINESS_NAMES = False
    p = Pseudonymiser(client, vendors=[])
    row = p.row(txn("UPI/P2M/092928654106/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD"))
    assert row.counterparty.startswith("P")
    assert "ZERODHA" not in row.narration


def test_amounts_go_out_as_bands_only(client):
    p = Pseudonymiser(client, vendors=[])
    row = p.row(txn("UPI/P2M/1/SOMEONE/x/BANK", paise=1_53_49_000))
    assert row.amount_band == "₹1–10 lakh"
    assert "15349" not in str(row.as_prompt_dict())


@pytest.mark.parametrize(
    ("paise", "band"),
    [(5000, "under ₹100"), (99_900, "₹100–1,000"), (5_00_000, "₹1,000–10,000"),
     (50_00_000, "₹10,000–1 lakh"), (5_00_00_000, "₹1–10 lakh"), (50_00_00_000, "over ₹10 lakh")],
)
def test_bands(paise, band):
    assert amount_band(paise) == band


@pytest.mark.parametrize(
    ("name", "person"),
    [
        ("MADHUKAR BALAJI JADHAV", True),
        ("Sunita Ramesh D", True),
        ("RameshGopalDeshmukh", True),
        ("ZERODHA BROKING LIMIT", False),
        ("Wipro Ge Health", True),  # errs towards person: no marker word
        ("GODAVARI_RESTAURANT", False),
        ("Medical officer of Health, NWCMC, N", False),
        ("Interest Paid", False),
        ("Credit Card 0000", False),
    ],
)
def test_person_heuristic_errs_towards_privacy(name, person):
    assert looks_like_a_person(name) is person


def test_aliases_are_stable_within_a_firm_and_differ_across_firms():
    a = person_alias("Madhukar Balaji Jadhav", "firm-1")
    assert a == person_alias("MADHUKAR BALAJI  JADHAV", "firm-1")
    assert a != person_alias("Madhukar Balaji Jadhav", "firm-2")
