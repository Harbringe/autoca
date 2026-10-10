"""Whether a party's name is found in the narrations banks actually print (invented figures, real shapes)."""

import pytest

from ledger.matching import _says, _squash

NAMES = [_squash("Ravi Traders Pvt Ltd")]


@pytest.mark.parametrize(
    "narration",
    [
        "NEFT-HDFCN52025061234567-RAVI TRADERS PVT LTD-INV 42-HDFC0001234",
        "UPI/512345678901/Ravi Traders Pvt Ltd/ravi@okhdfc/Payment",
        "IMPS/P2A/512345678901/RAVI TRADERS PVT LTD/HDFC",
        "RTGS-ICIC0001234-RAVI TRADERS PVT LTD-SETTLEMENT",
        "BIL/INFT/EDC0123456/RAVI TRADERS PVT LTD",
    ],
)
def test_the_full_name_is_found_in_the_usual_shapes(narration):
    assert _says(narration, NAMES)


@pytest.mark.parametrize(
    "narration",
    [
        "NEFT-HDFCN52025061234567-RAVI TRADING CO-INV 42",
        "UPI/512345678901/Ravi/ravi@okhdfc/Payment",
        "ATM-CASH WDL RAVI TRADERS ROAD BRANCH",
    ],
)
def test_a_different_or_partial_name_is_not_taken_for_it(narration):
    assert not _says(narration, NAMES)
