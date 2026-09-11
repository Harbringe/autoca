"""Reading structure out of real bank narration lines.

Every ``raw`` string below is from a real Axis statement, with names and
identifiers substituted. The variety is the point: a classifier that works on
the tidy examples and not on ``GODAVARI_RESTAU RANT_`` is a classifier that
sends a third of every statement to the review queue.
"""

from __future__ import annotations

import pytest

from classify.narration import Channel, analyse, normalise

HOLDER = "RAMESH GOPAL DESHMUKH"
OWN_ACCOUNTS = ["911010000004321"]


def facts(narration: str):
    return analyse(narration, HOLDER, OWN_ACCOUNTS)


@pytest.mark.parametrize(
    ("raw", "channel", "counterparty"),
    [
        (
            "UPI/P2M/092928654106/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD",
            Channel.UPI,
            "ZERODHA BROKING LIMIT",
        ),
        (
            "UPI/P2A/165532563485/MADHUKAR BALAJIRAO JADHAV/Meter/HDFC BANK LTD",
            Channel.UPI,
            "MADHUKAR BALAJIRAO JADHAV",
        ),
        ("MOB/TPFT/SUNITA RAMESH D/911010000004322", Channel.TRANSFER, "SUNITA RAMESH D"),
        (
            "NEFT/U000000988763903/Sovereign Gold Bonds Interes/RESERVE BANK OF INDI/",
            Channel.NEFT,
            "Sovereign Gold Bonds Interes",
        ),
        (
            "IMPS/P2A/534962100164/RameshGopalDeshmukh/X001676/HDFCBANKLTD/",
            Channel.IMPS,
            "RameshGopalDeshmukh",
        ),
        (
            "BRN-CLG-CHQ PAID TO Johnson Lifts P/KOTAK MAHINDRA",
            Channel.CHEQUE,
            "Johnson Lifts P",
        ),
        ("Clg/WIPRO GE HEALTHCARE PVT/HONGKONG and S", Channel.CHEQUE, "WIPRO GE HEALTHCARE PVT"),
        ("TRF/318/SHOBHA GOPAL /Shobha Gopal", Channel.TRANSFER, "SHOBHA GOPAL"),
        ("INB/134762494/INTERNET TAX PAYMENT/", Channel.TAX, "INTERNET TAX PAYMENT"),
        (
            "DD ISSUED/DIBG/Medical officer of Health, NWCMC, N",
            Channel.INSTRUMENT,
            "Medical officer of Health, NWCMC, N",
        ),
    ],
)
def test_counterparty_is_read_from_the_channel_template(raw, channel, counterparty):
    result = facts(raw)

    assert result.channel == channel
    assert result.counterparty == counterparty


def test_the_reference_is_separated_from_the_payee():
    """The reference is unique per transaction, so a rule keyed on it is dead on arrival."""
    result = facts("UPI/P2M/092928654106/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD")

    assert result.reference == "092928654106"
    assert result.counterparty == "ZERODHA BROKING LIMIT"
    assert result.counterparty_bank == "HDFC BANK LTD"
    assert result.remark == "098336"


def test_two_payments_to_one_payee_share_a_match_key():
    """The property the whole design rests on: one rule covers a payee forever."""
    first = facts("UPI/P2A/102648640341/NPCI BHIM/HDFC/BHIMCASH/")
    second = facts("UPI/P2A/103414340591/NPCI BHIM/HDFC/BHIMCASH/")

    assert first.raw != second.raw
    assert first.match_key == second.match_key


def test_channels_without_a_named_payee_still_get_a_party():
    """Otherwise every card repayment and interest credit queues for review forever."""
    assert facts("CreditCard Payment XX 1553 Ref#GFYPDNWLV474ZO").counterparty == "Credit Card 1553"
    assert facts("CRD-PMNT-440006****1553").counterparty == "Credit Card 1553"
    assert facts("SB:911010000004321:Int.Pd:01-04-2025 to 30-06-2025").counterparty == "Interest Paid"
    assert facts("Sweep/VO000000087559330/19000014841287").counterparty == "Sweep"


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
    result = facts("RTGS/HDFCR52025050266560113/DR RAMESH GOPAL DESHMUK/HDFC BANK///Self//OP")

    assert result.is_self_transfer


def test_a_transfer_to_the_holders_own_account_number_is_self():
    assert facts("UPI/P2M/109203143105/911010000004321/160226/ICICI Bank").is_self_transfer


@pytest.mark.parametrize(
    "spelling",
    [
        "NEFT/MB/AXOMB20402110637/Ramesh Gopal Deshmukh/HDFC BANK/OTHERS",
        "IMPS/P2A/534962100164/RameshGopalDeshmukh/X001676/HDFCBANKLTD/",
        # The bank truncates to the column width mid-name.
        "RTGS/HDFCR52025050266560113/DR RAMESH GOPAL DESHMUK/HDFC BANK",
    ],
)
def test_the_holders_name_is_matched_across_the_banks_own_spellings(spelling):
    """One statement spells its own customer three ways. Exact matching finds one."""
    assert facts(spelling).is_self_transfer


@pytest.mark.parametrize(
    "relative",
    [
        "UPI/P2A/193203854210/ADITYA RAMESH DESHMUKH /Simba/Kotak Mahindra Bank",
        "MOB/TPFT/SUNITA RAMESH D/911010000004322",
        "MOB/TPFT/VIKAS GOPAL D/911010000004323",
        "TRF/318/SHOBHA GOPAL /Shobha Gopal",
    ],
)
def test_a_relative_sharing_a_surname_is_not_the_holder(relative):
    """The expensive false positive: family transfers are drawings, not a contra."""
    assert not facts(relative).is_self_transfer


def test_interest_credited_by_the_bank_is_not_a_self_transfer():
    """It names the account number, but it is income. Treating it as a contra drops it."""
    result = facts("SB:911010000004321:Int.Pd:01-04-2025 to 30-06-2025")

    assert result.channel == Channel.INTEREST
    assert not result.is_self_transfer


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_normalisation_survives_a_wrap_landing_mid_token():
    """The bank wraps at the column edge, not at a word boundary."""
    wrapped = facts("UPI/P2M/001422314293/GODAVARI_RESTAU RANT_ /Hotel/YES BANK LIMITED YBS")

    assert normalise(wrapped.counterparty) == "GODAVARIRESTAURANT"


def test_normalisation_ignores_the_banks_own_inconsistency():
    assert normalise("Ramesh Gopal Deshmukh") == normalise("RAMESHGOPALDESHMUKH")
    assert normalise("ZERODHA BROKING LIMIT") == normalise("Zerodha Broking Limit")


def test_an_unrecognised_narration_degrades_rather_than_guessing():
    result = analyse("SOMETHING ENTIRELY NEW 12345")

    assert result.channel == Channel.UNKNOWN
    assert not result.is_recognised
    assert result.raw == "SOMETHING ENTIRELY NEW 12345"
    assert result.match_key == "SOMETHINGENTIRELYNEW12345"
