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
        ("UPI-SAMPLEPERSONNAME", Channel.UPI, "SAMPLEPERSONNAME"),
        ("UPI-SAMPLE PERSON NAME", Channel.UPI, "SAMPLE PERSON NAME"),
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


@pytest.mark.parametrize("raw", ["UPI-REFUND", "UPI-REVERSAL", "UPI-123456", "UPI-AB"])
def test_a_bare_upi_line_that_is_the_bank_speaking_or_has_no_name_names_no_payee(raw):
    """Only a name after ``UPI-`` is a payee; a refund or reversal, a number, or two letters are not."""
    assert analyse(raw).counterparty == ""


@pytest.mark.parametrize("raw", ["UPI-CHARGES", "UPI-GST ON CHARGES"])
def test_a_bare_upi_line_about_charges_is_still_a_fee(raw):
    assert analyse(raw).channel == Channel.FEE


def test_a_bare_upi_name_is_one_payee_whichever_month_it_comes_in():
    assert analyse("UPI-SAMPLEPERSONNAME").match_key == analyse("UPI-SAMPLEPERSONNAME").match_key != ""


def test_a_monthly_mandate_keeps_one_payee_whatever_the_instalment():
    assert analyse("NACH DR-TATA CAPITAL-EMI 12").match_key == analyse("NACH DR-TATA CAPITAL-EMI 13").match_key


# ---------------------------------------------------------------------------
# Other banks' shapes. Every value below is made up; only the shapes are real.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, channel, payee",
    [
        ("ACH/EXAMPLE POWER LTD/100001", Channel.MANDATE, "EXAMPLE POWER LTD"),
        ("APBS/SAMPLE GAS SUBSIDY/P0100000AA00", Channel.MANDATE, "SAMPLE GAS SUBSIDY"),
        ("UPI/Test Shop/testshop.9@upi/Dinner Bil/EXAMPLE BANK/100000000001/ABC123", Channel.UPI, "Test Shop"),
        ("UPI/Mr Demo Payer/9000000000@ybl/Payment fr/EXAMPLE BANK/100000000002/XYZ", Channel.UPI, "Mr Demo Payer"),
        ("MMT/IMPS/100000000001/Rent/RAMA DEMO/SBIN0000001", Channel.IMPS, "RAMA DEMO"),
        ("MMT/IMPS/100000000002/To HDFC Ac/SAMPLE PERSON/HDFC0000001/chgRs5.00GSTRs0.90", Channel.IMPS, "SAMPLE PERSON"),
        ("BIL/BPAY/0000001AAAA1/BBPS/Sample Telco/915831", Channel.BILL, "Sample Telco"),
        ("BIL/ONL/100000000001/DEMOINSURA/1000000000001/Policy 0000", Channel.BILL, "DEMOINSURA"),
        ("BIL/NEFT/IN10000000000001/Note/ANY PERSON/EXAMPLE BANK", Channel.NEFT, "ANY PERSON"),
        ("INF/NEFT/IN 400000001 00001/KKBK 0000001/sample payee...", Channel.NEFT, "sample payee"),
        ("INF/NEFT/IN 400000001 00002/HDF C0000001/demo name", Channel.NEFT, "demo name"),
        ("NEFT-HDFCH00000000001-DEMO CLEARING CORPORATION LIMITED-0001-00000000000001- HDFC0000001", Channel.NEFT, "DEMO CLEARING CORPORATION LIMITED"),
        ("NEFT- AXOMB000 00000001- SAMPLE TEXTILE-- 100000...", Channel.NEFT, "SAMPLE TEXTILE"),
        ("VPS/4303 SAMPLE MART /202601010000/100000000001/CITY", Channel.POS, "SAMPLE MART"),
        ("VIN/WWW EXAMPLE /202508280000/100000000001/", Channel.POS, "EXAMPLE"),
        ("DEPTFRUPI/CR/100000000001/SAMPLE", Channel.UPI, "SAMPLE"),
        ("WDL TFR UPI/DR/100000000002/DEMO PAYEE/EXAMPLE", Channel.UPI, "DEMO PAYEE"),
        ("TO TRANSFER-UPI/DR/100000000003/DEMO PAYEE/", Channel.UPI, "DEMO PAYEE"),
        ("CAM/00001ABC/CASH WDL/08-11-25", Channel.CASH, "CASH WDL"),
        ("CASHDEPOSITSELFAT00000SAMPLETOWN", Channel.CASH, "CASHDEPOSIT"),
    ],
)
def test_other_real_world_shapes_name_the_channel_and_the_payee(raw, channel, payee):
    found = analyse(raw)
    assert found.channel == channel
    assert found.counterparty == payee


@pytest.mark.parametrize(
    "raw",
    [
        # reference first: who the payee is varies by row, so none is read
        "UPI/100000 000001/Payment from Ph/9000000000@ybl/Ko",
        # a bare VPA first
        "UPI/qa00000000@ybl/Car Diesel/EXAMPLE BANK/100000000002/ICI0001",
        # a payer's note and a bank, with no IFSC to say which field is the payee
        "MMT/IMPS/100000000003/Payout/API Bankin",
        "MMT/IMPS/100000000004/Myself to icici/ANY PERSON/EXAMPLE Bank",
    ],
)
def test_where_the_field_order_varies_the_payee_is_not_guessed(raw):
    """A guessed payee becomes a rule key, and one decision would then place unrelated rows."""
    found = analyse(raw)
    assert found.is_recognised
    assert found.counterparty == ""


def test_the_fallback_names_the_channel_never_a_payee():
    found = analyse("ACH SOMETHING IN A SHAPE NOBODY TAUGHT 12345")
    assert found.channel == Channel.MANDATE
    assert found.counterparty == ""
    assert analyse("POS 000000****0000 EXAMPLE STORE").channel == Channel.POS
    assert analyse("POS 000000****0000 EXAMPLE STORE").counterparty == ""


def test_a_leading_word_that_only_starts_like_a_channel_is_not_one():
    assert analyse("CASHFREE PAYMENTS INDIA").channel == Channel.UNKNOWN
    assert analyse("UPIDEMO SERVICES").channel == Channel.UNKNOWN


def test_a_banks_own_interest_credit_is_income_not_a_transfer_to_the_other_account():
    """The account number in front of Int.Pd once made it a self-transfer, so it landed in the other bank's ledger."""
    found = analyse("000000000001:Int.Pd:01-01-2026 to 31-03-2026", HOLDER, ["000000000001"])
    assert found.channel == Channel.INTEREST
    assert not found.is_self_transfer
    assert "INTEREST" in found.hints


@pytest.mark.parametrize(
    "raw",
    [
        "MMT/IMPS/100000000004/Myself to icici/ANY PERSON/EXAMPLE Bank",
        "BIL/NEFT/IN10000000000001/Myself to HDFC/ANY PERSON/EXAMPLE BANK",
    ],
)
def test_a_note_saying_myself_marks_a_transfer_between_the_holders_own_accounts(raw):
    assert analyse(raw).is_self_transfer


def test_dividends_are_one_payee_whatever_the_year_or_instalment():
    keys = {
        analyse(raw).match_key
        for raw in (
            "ACH/SAMPLECO-FIN-DIV 24-25/SC0409250000001",
            "ACH/SAMPLECO-INT-DIV 25-26/SC0711250000002",
            "ACH/SAMPLECO-2ND INT-DIV 25-/SC0602260000003",
            "ACH/SAMPLECO INTERIM DIV25 26/00000000000000100001",
            "ACH/SAMPLECODIV07072025/1000001",
        )
    }
    assert keys == {normalise("SAMPLECO")}


@pytest.mark.parametrize(
    "raw, hints",
    [
        ("ACH/SAMPLECO-FIN-DIV 24-25/SC0409250000001", {"DIVIDEND"}),
        ("ACH/SAMPLECODIV07072025/1000001", {"DIVIDEND"}),
        ("APBS/SAMPLE GAS SUBSIDY/P0100000AA00", {"SUBSIDY"}),
        ("UPI/Test Shop/shop@upi/REFUND/EXAMPLE BANK/100000000001/A", {"REFUND"}),
        ("CAM/00001ABC/CASH WDL RVSL/08-11-25", {"REVERSAL"}),
        ("MMT/IMPS/100000000002/To HDFC Ac/SAMPLE PERSON/HDFC0000001/chgRs5.00GSTRs0.90", {"CHARGES_INCLUDED"}),
        ("UPI/Test Pump/pump@upi/petrol/EXAMPLE BANK/100000000001/A", {"FUEL"}),
        ("UPI/NETFLIX/netflix.bdauto/UPI Mandat/EXAMPLE BANK/100000000001/A", {"SUBSCRIPTION", "RECURRING"}),
        ("BIL/BPAY/0000001AAAA1/BBPS/Vi Postpai/915831", {"TELECOM", "BILL_PAYMENT"}),
    ],
)
def test_purpose_words_are_reported_as_canonical_hints(raw, hints):
    assert set(analyse(raw).hints) == hints


@pytest.mark.parametrize(
    "raw",
    [
        "UPI/DIVYA STORES/shop@upi/Bill/EXAMPLE BANK/100000000001/A",
        "UPI/INTERNET CAFE/cafe@upi/Bill/EXAMPLE BANK/100000000001/A",
        "ACH/INTERIM TRADING LTD/100001",
        "ACH/DEMO PETROLEUM COR/1795000",
        "UPI/VIKAS STORES/shop@upi/Bill/EXAMPLE BANK/100000000001/A",
    ],
)
def test_a_hint_needs_the_whole_word(raw):
    """DIVYA is a name, INTERNET and INTERIM are not interest, PETROLEUM is a company and not a fuel purchase."""
    assert analyse(raw).hints == ()


def test_hints_are_the_canonical_word_never_the_text_that_matched():
    for raw in ("UPI/Test Pump/pump@upi/petrol/EXAMPLE BANK/100000000001/A", "ACH/SAMPLECODIV07072025/1000001"):
        for hint in analyse(raw).hints:
            assert hint.isupper() and hint.replace("_", "").isalpha()


def test_a_page_footer_glued_onto_a_narration_is_not_part_of_it():
    clean = analyse("ACH/EXAMPLE LTD/100001")
    glued = analyse("ACH/EXAMPLE LTD/100001 www.example.bank.in Dial your Bank call from your registered mobile number")
    assert glued.raw == clean.raw
    assert glued.match_key == clean.match_key
    assert analyse("UPI/Test Shop/shop@upi/Bill/EXAMPLE BANK/100000000001/A Legends for transactions in your Account XYZ").raw.endswith("/A")


def test_a_note_with_fee_or_gst_in_it_is_a_payment_not_a_bank_charge():
    """The generic fee pattern comes last, so a school-fee UPI is a UPI payment and no seed rule posts it to Bank Charges."""
    found = analyse("UPI/Test School/school@upi/School fee/EXAMPLE BANK/100000000001/A")
    assert found.channel == Channel.UPI
    assert found.channel != Channel.FEE


def test_lines_read_by_position_keep_their_text_back():
    assert analyse("UPI/Test Shop/shop@upi/Bill/EXAMPLE BANK/100000000001/A").withhold_text
    assert analyse("ACH/EXAMPLE LTD/100001").withhold_text
    # the older, fully understood shapes still send their masked text as before
    assert not analyse("UPI/P2M/100000000001/ZERODHA BROKING LIMIT/098336/HDFC BANK LTD").withhold_text


@pytest.mark.parametrize(
    "raw",
    [
        "UPI/DR/100000000001/DEMO NAME/EXAMPLE BANK/x@upi/note",
        "UPI/CR/100000000001/DEMO NAME/EXAMPLE BANK/x@upi/note",
        "ACH/DR/100001",
        "ACH/MANDATE/100001",
        "MMT/IMPS/100000000001/Rent/NA/SBIN0000001",
    ],
)
def test_a_structural_word_is_never_read_as_the_payee(raw):
    """A payee of "DR" would become a rule key, and one decision would place every UPI debit."""
    found = analyse(raw)
    assert found.is_recognised
    assert found.counterparty == ""


@pytest.mark.parametrize("raw", ["CAM/00001ABC/SOMETHING ELSE", "NFS/CASH WDL/0001", "VAT/100001/ATM", "MAT/100001/ATM", "ATM 100001 SOMEWHERE"])
def test_cash_is_only_claimed_by_a_shape_that_has_been_seen(raw):
    """A seed rule posts cash rows to Cash-in-Hand unseen, so a guess here would book bank rows as cash."""
    assert analyse(raw).channel != Channel.CASH
