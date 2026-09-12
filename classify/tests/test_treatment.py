"""Vendors, tax treatment, and the confidence bands the review screen sorts by.

The thing being defended: a bookkeeping decision is four facts, not one, and
they are learned together. A loop that remembers the ledger and forgets the
reverse-charge flag looks like it works, right up to the point a return is
prepared from books missing half their RCM entries.
"""

from __future__ import annotations

import datetime

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue, review_summary, vendor_for
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    LedgerGroup,
    TransactionClassification,
    Vendor,
)
from classify.seeds import seed_client
from classify.treatment import ReviewBand, TdsSection, Treatment, band_for
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def client():
    firm = create_firm("Treatment Test Firm")
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


@pytest.fixture
def statement(client):
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        yield statement


def ledger(client, name, group=LedgerGroup.INDIRECT_EXPENSE):
    return LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name=name, group=group
    )


def queued(client, fragment):
    return review_queue(client).filter(transaction__narration__icontains=fragment).first()


# ---------------------------------------------------------------------------
# The four facts travel together
# ---------------------------------------------------------------------------


def test_a_treatment_carries_ledger_party_rcm_and_tds(client, statement):
    freight = ledger(client, "Freight Inward", LedgerGroup.DIRECT_EXPENSE)
    carrier = vendor_for(client, "Speedy Goods Transport", rcm=True)

    row = queued(client, "Johnson Lifts")
    review(row, Treatment(ledger=freight, vendor=carrier, rcm=True, tds_section=TdsSection.CONTRACTOR))
    row.refresh_from_db()

    assert row.ledger_id == freight.pk
    assert row.vendor_id == carrier.pk
    assert row.rcm
    assert row.tds_section == "194C"


def test_the_whole_treatment_is_learned_not_just_the_ledger(client, statement):
    """The bug this prevents: RCM remembered nowhere, re-decided every month."""
    freight = ledger(client, "Freight Inward", LedgerGroup.DIRECT_EXPENSE)
    carrier = vendor_for(client, "Speedy Goods Transport")

    _, rule = review(
        queued(client, "Johnson Lifts"),
        Treatment(ledger=freight, vendor=carrier, rcm=True, tds_section=TdsSection.CONTRACTOR),
    )

    assert rule.ledger_id == freight.pk
    assert rule.vendor_id == carrier.pk
    assert rule.rcm
    assert rule.tds_section == "194C"


def test_changing_one_part_of_a_treatment_updates_all_of_it(client, statement):
    """A reviewer clearing the RCM flag must not leave the rule still setting it."""
    expenses = ledger(client, "Office Expenses")
    review(queued(client, "Blinkit"), Treatment(ledger=expenses, rcm=True))

    corrected = TransactionClassification.objects.get(
        firm_id=client.firm_id, transaction__narration__icontains="Blinkit"
    )
    review(corrected, Treatment(ledger=expenses, rcm=False))

    rule = ClassificationRule.objects.get(ledger=expenses)
    assert not rule.rcm
    corrected.refresh_from_db()
    assert not corrected.rcm


def test_a_treatment_without_a_ledger_cannot_be_built():
    """Unplaced is a separate state, not a treatment with a hole in it."""
    with pytest.raises(ValueError, match="needs a ledger head"):
        Treatment(ledger=None)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def test_a_vendor_is_reused_across_spellings(client):
    """The bank's inconsistent spacing must not produce three vendors for one payee."""
    with firm_context(client.firm_id):
        first = vendor_for(client, "WIPRO GE HEALTHCARE PVT")
        again = vendor_for(client, "Wipro  Ge   Healthcare Pvt")

        assert again.pk == first.pk
        assert Vendor.objects.count() == 1


def test_a_vendor_gets_a_stable_pseudonym(client):
    """What a language model sees instead of the name, when that step lands."""
    with firm_context(client.firm_id):
        vendor = vendor_for(client, "WIPRO GE HEALTHCARE PVT")

        assert vendor.alias_token.startswith("V")
        assert "WIPRO" not in vendor.alias_token
        assert vendor.alias_token == Vendor.make_alias(
            "WIPRO GE HEALTHCARE PVT", client.firm_id
        )


def test_a_vendor_gstin_is_encrypted_but_still_matchable(client):
    """GST reconciliation joins on vendor GSTIN, which is ciphertext."""
    with firm_context(client.firm_id):
        vendor = vendor_for(client, "Wipro GE Healthcare")
        vendor.set_gstin("29AAACW1234F1Z5")
        vendor.save()
        vendor.refresh_from_db()

        assert b"29AAACW" not in bytes(vendor.gstin_enc)
        assert vendor.gstin == "29AAACW1234F1Z5"
        assert len(vendor.gstin_hash) == 64


def test_vendor_defaults_carry_the_tax_treatment(client):
    """Reverse charge is a property of who you are paying, not of the category."""
    with firm_context(client.firm_id):
        carrier = vendor_for(client, "Speedy Goods Transport", rcm=True, tds_section="194C")

        assert carrier.rcm_default
        assert carrier.tds_section == "194C"


# ---------------------------------------------------------------------------
# Confidence and the review queue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (1.0, ReviewBand.HIGH),
        (0.95, ReviewBand.HIGH),
        (0.90, ReviewBand.HIGH),
        (0.89, ReviewBand.ADVISED),
        (0.75, ReviewBand.ADVISED),
        (0.74, ReviewBand.JUDGEMENT),
        (0.0, ReviewBand.JUDGEMENT),
    ],
)
def test_confidence_maps_to_a_band(confidence, expected):
    assert band_for(confidence) == expected


def test_a_seeded_rule_asserts_rather_than_suggests(client, statement):
    """"Interest the bank paid is income" is true in every set of books."""
    interest = review_queue(client).filter(channel="INTEREST").first()

    assert interest.confidence >= 0.90
    assert interest.review_band == ReviewBand.HIGH


def test_an_unmatched_row_claims_nothing(client, statement):
    """A confident wrong answer is worse than an honest "I don't know"."""
    unknown = review_queue(client).filter(counterparty="Smallcase").first()

    assert unknown.confidence == 0.0
    assert unknown.review_band == ReviewBand.JUDGEMENT
    assert unknown.ledger is None


def test_a_learned_payee_rule_is_high_confidence(client, statement):
    """It came from a person naming this exact payee. That is a strong claim."""
    cashback = ledger(client, "Bhim Cash Back", LedgerGroup.INDIRECT_INCOME)
    review(queued(client, "NPCI BHIM"), cashback)

    siblings = review_queue(client).filter(ledger=cashback)
    assert siblings.exists()
    assert all(row.review_band == ReviewBand.HIGH for row in siblings)


def test_the_review_summary_splits_the_work_by_how_much_thought_it_needs(client, statement):
    """The ordering is the feature: it turns an hour of checking into minutes."""
    summary = review_summary(client)

    assert summary.total == 54
    assert summary.high == 4  # the seeded interest rows
    assert summary.judgement == 50
    assert summary.bulk_approvable == summary.high


def test_the_queue_puts_the_surest_rows_first(client, statement):
    confidences = [row.confidence for row in review_queue(client)]

    assert confidences == sorted(confidences, reverse=True)


def test_a_resolved_row_leaves_the_queue_entirely(client, statement):
    """A suggestion is still work in hand; a decision is not."""
    before = review_queue(client).count()
    review(queued(client, "INTERNET TAX PAYMENT"), ledger(client, "Advance Tax", LedgerGroup.DUTIES_AND_TAXES))

    assert review_queue(client).count() == before - 1
