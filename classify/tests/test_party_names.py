"""Which payee names are plainly a person or a business, so their own account may be opened without asking. No database."""

import pytest

from classify.party_discovery import looks_like_a_party


@pytest.mark.parametrize("name", ["Sample Traders", "Ravi Kumar Sharma", "Om Traders", "Test Textiles Pvt Ltd"])
def test_clear_names_pass(name):
    assert looks_like_a_party(name)


@pytest.mark.parametrize(
    "name",
    ["ASHOK", "8999938089@ybl", "BY CASH", "Interest Collected", "Charges for PORD Customer Payment", "UPI Payments", "Person 12345", "a/b c", "R K", "XXXXXXXXXX3 300", ""],
)
def test_one_word_handles_channels_and_masked_names_do_not(name):
    assert not looks_like_a_party(name)


# ---------------------------------------------------------------------------
# A bank's spelling against a Tally ledger name
# ---------------------------------------------------------------------------

from classify.party_discovery import is_collector, reads_as, tidy_name  # noqa: E402


@pytest.mark.parametrize(
    ("bank", "ledger"),
    [
        ("SAMPLE TRADERS", "Sample Traders Gujarat"),
        ("SAMPLE SILKS", "M/s Sample Silks ,AndhraPradesh"),
        ("SAMPLE COTTON MILL PVT L", "Sample Cotton Mill Pvt Ltd,Kolhapur"),
        ("SAMPLE ENTERPRISE", "Sample Enterprises , Gujarat"),
        ("M S SAMPLE GANPATI SALES ENTE", "Sample Ganpati Sales Enterprises"),
        ("SAMPLE TEXTILES", "Sample Textiles"),
    ],
)
def test_a_bank_spelling_reads_as_the_tally_name_it_starts(bank, ledger):
    assert reads_as(bank, ledger)


@pytest.mark.parametrize(
    ("bank", "ledger"),
    [
        ("SAMPLE", "Sample Traders"),  # one word is a first name, not a business
        ("SAMPLE TEXTILES", "Other Sample Textiles"),  # not the start of it
        ("SAMPLE TRADERS GUJARAT", "Sample Traders"),  # longer than the ledger
        ("SAMPLE TRAVELS", "Sample Traders"),
    ],
)
def test_other_names_do_not(bank, ledger):
    assert not reads_as(bank, ledger)


def test_a_bank_name_is_tidied_for_its_ledger():
    assert tidy_name("M S SAMPLE GANPATI SALES") == "Sample Ganpati Sales"
    assert tidy_name("AV HANDLOOM") == "AV Handloom"
    assert tidy_name("Sample Traders, Pune") == "Sample Traders, Pune"


@pytest.mark.parametrize("name", ["GOOGLE INDIA DIGITAL SERVICE", "PAYTM PAYMENTS", "Razorpay Software"])
def test_payment_collectors_are_not_customers(name):
    assert is_collector(name)
    assert not is_collector("Sample Traders")


@pytest.mark.parametrize("name", ["R S DESIGNER", "J J EXPORT"])
def test_initials_pass_when_the_name_says_the_trade(name):
    assert looks_like_a_party(name)


# Spellings that real statements and Tally ledgers disagree on. Made-up names, same shapes.
@pytest.mark.parametrize(
    ("bank", "ledger"),
    [
        ("SAMPLE SILK MILLS", "Sample Silk Mill, Gujarat"),  # a plural, and a town the bank leaves off
        ("S T SYNTHETICS", "S T SYNTHETIC, RAJASTHAN"),
        ("SAMPLE CAP DEPOT PRIVATE LT", "Sample Cap Depot Pvt Ltd"),  # cut off
        ("SAMPLEX CAP DEPOT", "Samplax Cap Depot Pvt Ltd"),  # one letter off in a long word
        ("SAMPLE TEXTILE MARKET PEIVATE", "Sample Textile Market Pvt. Ltd."),  # a typo of PRIVATE
        ("SHREE SAMPLE TRADING CO H", "Shri Sample Trading Co"),  # Shree/Shri, and a cut-off "CO H"
    ],
)
def test_a_plural_a_slip_a_cut_off_or_a_town_does_not_make_a_second_ledger(bank, ledger):
    assert reads_as(bank, ledger)


@pytest.mark.parametrize(
    ("bank", "ledger"),
    [
        ("S T SYNTHETICS", "M T Synthetics"),  # initials must match exactly
        ("SAI PRINTS", "Sam Prints"),  # a slip in a short word is another name
        ("SAMPLE SILK MILLS", "Sample Silk Traders"),
        ("RAMESH TRADERS", "Rakesh Traders"),  # two real first names are not one typo
    ],
)
def test_but_another_name_is_still_another_name(bank, ledger):
    assert not reads_as(bank, ledger)
