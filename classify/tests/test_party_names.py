"""Which payee names are plainly a person or a business, so their own account may be opened without asking. No database."""

import pytest

from classify.party_discovery import looks_like_a_party


@pytest.mark.parametrize("name", ["Sample Traders", "Ravi Kumar Sharma", "Om Traders", "Test Textiles Pvt Ltd"])
def test_clear_names_pass(name):
    assert looks_like_a_party(name)


@pytest.mark.parametrize(
    "name",
    ["ASHOK", "8999938089@ybl", "BY CASH", "Charges for PORD Customer Payment", "UPI Payments", "Person 12345", "a/b c", "R K", "XXXXXXXXXX3 300", ""],
)
def test_one_word_handles_channels_and_masked_names_do_not(name):
    assert not looks_like_a_party(name)
