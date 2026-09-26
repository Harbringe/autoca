"""Reading structure out of real bank narration lines.

Every ``raw`` string below is from a real Axis statement, with names and
identifiers substituted. The variety is the point: a classifier that works on
the tidy examples and not on ``GODAVARI_RESTAU RANT_`` is a classifier that
sends a third of every statement to the review queue.
"""

from __future__ import annotations

import pytest

from classify.narration import Channel, analyse, normalise

HOLDER = "ARJUN PRATAP NAIR"
OWN_ACCOUNTS = ["900000000000001"]


def facts(narration: str):
    return analyse(narration, HOLDER, OWN_ACCOUNTS)


@pytest.mark.parametrize(
    ("raw", "channel", "counterparty"),
    [
        (
            "UPI/P2M/100000000001/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD",
            Channel.UPI,
            "ZERODHA BROKING LIMIT",
        ),
        (
            "UPI/P2A/100000000003/SURESH KIRAN MENON/Meter/HDFC BANK LTD",
            Channel.UPI,
            "SURESH KIRAN MENON",
        ),
        ("MOB/TPFT/PRIYA ARJUN N/900000000000002", Channel.TRANSFER, "PRIYA ARJUN N"),
        (
            "NEFT/U000000100000001/Sovereign Gold Bonds Interes/RESERVE BANK OF INDI/",
            Channel.NEFT,
            "Sovereign Gold Bonds Interes",
        ),
        (
            "IMPS/P2A/100000000002/ArjunPratapNair/X000001/HDFCBANKLTD/",
            Channel.IMPS,
            "ArjunPratapNair",
        ),
        (
            "BRN-CLG-CHQ PAID TO Johnson Lifts P/KOTAK MAHINDRA",
            Channel.CHEQUE,
            "Johnson Lifts P",
        ),
        ("Clg/WIPRO GE HEALTHCARE PVT/HONGKONG and S", Channel.CHEQUE, "WIPRO GE HEALTHCARE PVT"),
        ("TRF/318/MEERA PRATAP /Meera Pratap", Channel.TRANSFER, "MEERA PRATAP"),
        ("INB/100000009/INTERNET TAX PAYMENT/", Channel.TAX, "INTERNET TAX PAYMENT"),
        (
            "DD ISSUED/DIBG/Medical officer of Health, CMC, N",
            Channel.INSTRUMENT,
            "Medical officer of Health, CMC, N",
        ),
    ],
)
def test_counterparty_is_read_from_the_channel_template(raw, channel, counterparty):
    result = facts(raw)

    assert result.channel == channel
    assert result.counterparty == counterparty


def test_the_reference_is_separated_from_the_payee():
    """The reference is unique per transaction, so a rule keyed on it is dead on arrival."""
    result = facts("UPI/P2M/100000000001/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD")

    assert result.reference == "100000000001"
    assert result.counterparty == "ZERODHA BROKING LIMIT"
    assert result.counterparty_bank == "HDFC BANK LTD"
    assert result.remark == "098336"


def test_two_payments_to_one_payee_share_a_match_key():
    """The property the whole design rests on: one rule covers a payee forever."""
    first = facts("UPI/P2A/100000000006/NPCI BHIM/HDFC/BHIMCASH/")
    second = facts("UPI/P2A/100000000017/NPCI BHIM/HDFC/BHIMCASH/")

    assert first.raw != second.raw
    assert first.match_key == second.match_key


def test_channels_without_a_named_payee_still_get_a_party():
    """Otherwise every card repayment and interest credit queues for review forever."""
    assert facts("CreditCard Payment XX 1553 Ref#GFYPDNWLV474ZO").counterparty == "Credit Card 1553"
    assert facts("CRD-PMNT-440006****1553").counterparty == "Credit Card 1553"
    assert facts("SB:900000000000001:Int.Pd:01-04-2025 to 30-06-2025").counterparty == "Interest Paid"
    assert facts("Sweep/VO000000012345678/19000000000001").counterparty == "Sweep"


def test_card_repayments_group_by_card_regardless_of_narration_shape():
    """Three formats for the same card in one statement. All one ledger."""
    keys = {
        facts("CreditCard Payment XX 1553 Ref#GFYPDNWLV474ZO").match_key,
        facts("CRD-PMNT-440006****1553").match_key,
    }

    assert len(keys) == 1


# ---------------------------------------------------------------------------
# Self-transfers: a contra entry, not income or expenditure
# ---------------------------------------------------------------------------


def test_an_explicit_self_marker_is_honoured():
    result = facts("RTGS/HDFCR50000000000000001/DR ARJUN PRATAP NAI/HDFC BANK///Self//OP")

    assert result.is_self_transfer


def test_a_transfer_to_the_holders_own_account_number_is_self():
    assert facts("UPI/P2M/100000000018/900000000000001/160226/ICICI Bank").is_self_transfer


@pytest.mark.parametrize(
    "spelling",
    [
        "NEFT/MB/AXOMB10000000001/Arjun Pratap Nair/HDFC BANK/OTHERS",
        "IMPS/P2A/100000000002/ArjunPratapNair/X000001/HDFCBANKLTD/",
        # The bank truncates to the column width mid-name.
        "RTGS/HDFCR50000000000000001/DR ARJUN PRATAP NAI/HDFC BANK",
    ],
)
def test_the_holders_name_is_matched_across_the_banks_own_spellings(spelling):
    """One statement spells its own customer three ways. Exact matching finds one."""
    assert facts(spelling).is_self_transfer


@pytest.mark.parametrize(
    "relative",
    [
        "UPI/P2A/100000000019/VIKRAM ARJUN NAIR /Simba/Kotak Mahindra Bank",
        "MOB/TPFT/PRIYA ARJUN N/900000000000002",
        "MOB/TPFT/ROHIT PRATAP D/900000000000003",
        "TRF/318/MEERA PRATAP /Meera Pratap",
    ],
)
def test_a_relative_sharing_a_surname_is_not_the_holder(relative):
    """The expensive false positive: family transfers are drawings, not a contra."""
    assert not facts(relative).is_self_transfer


def test_interest_credited_by_the_bank_is_not_a_self_transfer():
    """It names the account number, but it is income. Treating it as a contra drops it."""
    result = facts("SB:900000000000001:Int.Pd:01-04-2025 to 30-06-2025")

    assert result.channel == Channel.INTEREST
    assert not result.is_self_transfer


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_normalisation_survives_a_wrap_landing_mid_token():
    """The bank wraps at the column edge, not at a word boundary."""
    wrapped = facts("UPI/P2M/100000000004/GODAVARI_RESTAU RANT_ /Hotel/YES BANK LIMITED YBS")

    assert normalise(wrapped.counterparty) == "GODAVARIRESTAURANT"


def test_normalisation_ignores_the_banks_own_inconsistency():
    assert normalise("Arjun Pratap Nair") == normalise("ARJUNPRATAPNAIR")
    assert normalise("ZERODHA BROKING LIMIT") == normalise("Zerodha Broking Limit")


def test_an_unrecognised_narration_degrades_rather_than_guessing():
    result = analyse("SOMETHING ENTIRELY NEW 12345")

    assert result.channel == Channel.UNKNOWN
    assert not result.is_recognised
    assert result.raw == "SOMETHING ENTIRELY NEW 12345"
    assert result.match_key == "SOMETHINGENTIRELYNEW12345"


@pytest.mark.parametrize(
    "raw",
    [
        "GST PAYMENT CPIN 25040012345678",
        "IB/GSTN/CPIN 25071200123456",
        "CBDT TAX PAYMENT ITNS 280",
        "OLTAS CHALLAN 281 TDS",
    ],
)
def test_a_tax_paid_through_the_bank_is_a_tax_payment_not_a_bank_charge(raw):
    """A GST challan once read as a fee, and a seed rule posted it to Bank Charges unseen."""
    assert analyse(raw).channel == Channel.TAX


@pytest.mark.parametrize("raw", ["GST ON CHARGES", "SMS ALERT CHARGES QTR", "ANNUAL FEE DEBIT CARD"])
def test_the_banks_own_charges_are_still_fees(raw):
    assert analyse(raw).channel == Channel.FEE


@pytest.mark.parametrize(
    "raw, channel, payee",
    [
        ("NEFT CR-HDFC0001234-ORBIT RETAIL PVT LTD-INV 1042", Channel.NEFT, "ORBIT RETAIL PVT LTD"),
        ("NEFT DR-SBIN0004321-SUNRISE PACKAGING CO-PO 77", Channel.NEFT, "SUNRISE PACKAGING CO"),
        ("RTGS CR-ICIC0000456-LOTUS DISTRIBUTORS LLP", Channel.RTGS, "LOTUS DISTRIBUTORS LLP"),
        ("UPI/410123456789/Payment to BigBasket", Channel.UPI, "BigBasket"),
        ("UPI/501234567890/SOME HOLDER/Payment to ZEPTO MARKETPLACE", Channel.UPI, "ZEPTO MARKETPLACE"),
        ("UPI-SWIGGY-9876543210", Channel.UPI, "SWIGGY"),
        ("ACH D- LIC OF INDIA", Channel.MANDATE, "LIC OF INDIA"),
        ("NACH DR-TATA CAPITAL-EMI 12", Channel.MANDATE, "TATA CAPITAL"),
        ("CHQ DEP-000412-CLEARING-MEHTA HARDWARE", Channel.CHEQUE, "MEHTA HARDWARE"),
    ],
)
def test_other_banks_formats_still_name_the_payee(raw, channel, payee):
    """Without a payee nothing can be learned: "Remember this" did nothing for these."""
    facts = analyse(raw)
    assert facts.channel == channel
    assert facts.counterparty == payee


def test_a_monthly_mandate_keeps_one_payee_whatever_the_instalment():
    assert analyse("NACH DR-TATA CAPITAL-EMI 12").match_key == analyse("NACH DR-TATA CAPITAL-EMI 13").match_key
